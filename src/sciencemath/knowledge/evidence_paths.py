"""Typed, exact-identity structured evidence paths; no inferred fact edges."""
from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass
from sciencemath.knowledge.evidence import EvidenceItem
from sciencemath.knowledge.relations import RelationId, canonical_relation, query_relations
from sciencemath.knowledge.injection import quarantine_source_text


def normalize_identity(value: object) -> str:
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())


def structured_entity_match(reference, item):
    entity = (getattr(item, 'metadata', None) or {}).get('fact_entity')
    return bool(entity) and normalize_identity(reference) == normalize_identity(entity)


def strict_text_identity(reference, text):
    runs = re.findall(r"(?<!\w)[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*", text)
    return normalize_identity(reference) in {normalize_identity(r) for r in runs}


@dataclass(frozen=True)
class FactEdge:
    subject_entity: str
    relation: RelationId
    object_value: str
    source_id: str
    chunk_id: str
    citation_id: str
    topic_tags: tuple[str, ...]
    authority_class: str
    freshness_class: str
    proposition: str
    content_hash: str

    @property
    def canonical_relation(self):
        return self.relation

    def to_dict(self):
        return {**self.__dict__, 'relation': str(self.relation),
                'canonical_relation': str(self.relation), 'topic_tags': list(self.topic_tags)}


@dataclass(frozen=True)
class EvidencePath:
    edges: tuple[FactEdge, ...]
    validation_trace: tuple[str, ...] = ('structured_edges', 'exact_identity', 'complete')

    def __post_init__(self):
        if not 1 <= len(self.edges) <= 2:
            raise ValueError('Evidence paths require one or two edges')
        if len(self.edges) == 2 and normalize_identity(self.edges[0].object_value) != normalize_identity(self.edges[1].subject_entity):
            raise ValueError('Bridge identity mismatch')

    @property
    def final_value(self):
        return self.edges[-1].object_value

    @property
    def hop_count(self):
        return len(self.edges)

    @property
    def source_ids(self):
        return sorted({e.source_id for e in self.edges})

    @property
    def citation_ids(self):
        return list(dict.fromkeys(e.citation_id for e in self.edges))

    @property
    def domain_tags(self):
        return sorted({tag for e in self.edges for tag in e.topic_tags})

    def to_dict(self):
        return {'start_entity': self.edges[0].subject_entity,
                'target_relation': str(self.edges[-1].relation),
                'required_sources': self.source_ids, 'required_domains': self.domain_tags,
                'citations': self.citation_ids, 'complete': True,
                'provenance_role': 'REASONING_PATH_PROVENANCE',
                'edges': [e.to_dict() for e in self.edges], 'final_value': self.final_value,
                'hop_count': self.hop_count, 'source_ids': self.source_ids,
                'citation_ids': self.citation_ids, 'domain_tags': self.domain_tags,
                'required_source_ids': self.source_ids, 'validation_trace': list(self.validation_trace)}


def project_fact_edge(item: EvidenceItem) -> FactEdge | None:
    """Require one safe sentence actually expressing all structured fact parts.

    Metadata alone cannot turn a removed instruction into a proposition.
    Full ordered entity/value strings must occur together with a relation cue.
    """
    meta = item.metadata or {}
    entity, value = meta.get('fact_entity'), meta.get('fact_value')
    relation = canonical_relation(meta.get('fact_attribute'))
    if not entity or value is None or not str(value).strip() or not relation:
        return None
    safe = quarantine_source_text(item.text_span)['safe_text']
    for sentence in re.split(r'(?<=[.!?])\s+', safe):
        normalized = normalize_identity(sentence)
        def present(part):
            return bool(re.search(r'(?<!\w)' + re.escape(normalize_identity(part)) + r'(?!\w)', normalized))
        if (present(entity) and present(value) and relation in query_relations(sentence)
                and not re.search(r'\b(?:not|never|false|incorrect|denied|denies)\b', normalized)):
            return FactEdge(str(entity), relation, str(value), item.source_id,
                            item.chunk_id, item.citation_id, tuple(item.topic_tags),
                            item.authority_class, item.freshness_class,
                            sentence.strip(), item.content_hash)
    return None

# Projection alias used by the pipeline: no parallel semantic metadata.
fact_edge = project_fact_edge


@dataclass(frozen=True)
class PathRequest:
    start_entity: str
    relations: tuple[RelationId, ...]


def parse_path_request(query):
    from sciencemath.knowledge.relations import parse_relation_path
    parsed = parse_relation_path(query)
    if parsed:
        return PathRequest(*parsed)
    return None


@dataclass
class PathResolution:
    request: PathRequest
    items: list
    selected: list
    trace: list
    conflicts: list
    status: str = 'INSUFFICIENT_EVIDENCE'

    def to_trace(self):
        return {'status': self.status, 'reason': self.trace[-1] if self.trace else self.status,
                'start_entity': self.request.start_entity,
                'requested_relations': [str(r) for r in self.request.relations],
                'first_retrieval': {'chunk_ids': [it.chunk_id for it in self.items]},
                'second_retrieval': [t for t in self.trace if t.startswith('second_retrieval:')],
                'validation_trace': self.trace or [self.status]}



def _choose(items, entity, relation):
    from sciencemath.knowledge.conflicts import AUTHORITY_RANK, _FRESHNESS_RANK
    eligible = [(it, fact_edge(it)) for it in items]
    eligible = [(it, edge) for it, edge in eligible if edge is not None
                and normalize_identity(edge.subject_entity) == normalize_identity(entity)
                and edge.canonical_relation == relation]
    if not eligible:
        return None, []
    def rank(pair):
        edge = pair[1]
        return AUTHORITY_RANK.get(edge.authority_class, 0), _FRESHNESS_RANK.get(edge.freshness_class, 0)
    best = max(map(rank, eligible))
    leaders = [(it, edge) for it, edge in eligible if rank((it, edge)) == best]
    if len({normalize_identity(edge.object_value) for _, edge in leaders}) > 1:
        first = leaders[0]
        other = next(p for p in leaders if normalize_identity(p[1].object_value) != normalize_identity(first[1].object_value))
        return None, [{'claim_key': f'{entity}|{relation}',
                       'evidence_a': first[0].to_dict(), 'evidence_b': other[0].to_dict()}]
    return leaders[0][0], []


def resolve_path(request, initial, corpus, query):
    from sciencemath.knowledge.evidence import items_from_chunks
    from sciencemath.knowledge.retrieval import retrieve_structured
    result = PathResolution(request, list(initial), [], [], [])
    if len(request.relations) not in (1, 2):
        result.trace.append('path:unsupported_length')
        return result
    first, conflicts = _choose(initial, request.start_entity, request.relations[0])
    if conflicts:
        result.conflicts, result.status = conflicts, 'CONFLICTING_EVIDENCE'
        return result
    if first is None:
        result.trace.append('path:hop1_missing')
        return result
    result.selected.append(first)
    if len(request.relations) == 1:
        result.status = 'ANSWER'
        result.trace.append('path:complete:1')
        return result
    bridge = str(first.metadata['fact_value'])
    target = request.relations[1]
    ranked, retrieval_trace = retrieve_structured(corpus.chunks_by_id, bridge, target)
    result.trace.append(f'second_retrieval:{bridge}:{target}:{len(ranked)}:local_structured')
    if retrieval_trace['overflow']:
        result.trace.append('second_retrieval:overflow:INSUFFICIENT_EVIDENCE')
        return result
    added = items_from_chunks(ranked, corpus.chunks_by_id, corpus.sources_by_id, query)
    seen = {it.chunk_id for it in result.items}
    result.items.extend(it for it in added if it.chunk_id not in seen)
    second, conflicts = _choose(result.items, bridge, target)
    if conflicts:
        result.conflicts, result.status = conflicts, 'CONFLICTING_EVIDENCE'
        return result
    if second is None:
        result.trace.append('path:hop2_missing')
        return result
    result.selected.append(second)
    result.status = 'ANSWER'
    result.trace.extend([f'multi_hop:2:{bridge}', 'path:complete:2'])
    return result
