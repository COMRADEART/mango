# Mango release reproducibility policy

Every promoted adapter must be independently retrievable and verifiable before
the production configuration or promotion decision changes. A local directory,
successful historical evaluation, or matching adapter configuration is insufficient.

## Required immutable release bundle

- The actual unmerged `adapter_model.safetensors`, its byte size and SHA-256.
- Git LFS storage with a committed pointer and verified remote object, or durable
  versioned release storage with an immutable object identifier and retention policy.
- Exact base model ID and commit revision; exact tokenizer ID and revision, tokenizer
  file hashes, and the chat template hash. Floating `main` is insufficient.
- Adapter configuration and a complete inventory of tensor names, shapes, dtypes,
  element counts, and total parameter count.
- Training provenance: code commit, environment, seed, dataset byte hashes, selected
  checkpoint, final training step, checkpoint-selection criterion and loss history.
- A reload smoke result produced from the retrieved artifact in a clean environment,
  proving the intended adapter is active on the pinned base with recorded quantization.
- An immutable release manifest containing all the above hashes, plus evaluation
  suite hashes, generation configuration, prediction hashes, evaluation code commit,
  exact collected test IDs, pytest results and promotion decision.

## Publication and verification

1. Compute the weight hash at checkpoint selection and persist it before evaluation.
   Every evaluation records that same weight hash; the release manifest binds it to
   the selected checkpoint and model/tokenizer revisions.
2. Check ignore rules explicitly. An LFS attribute does not override `.gitignore`.
   Add the selected artifact intentionally and inspect the staged content: an LFS
   pointer must contain the expected `oid sha256` and size, never raw model bytes.
3. Upload the LFS object (or immutable release object). Verify availability from a
   clean clone with an empty LFS/cache location, then compare retrieved bytes with
   the manifest SHA-256 and run the reload smoke. A local-cache hit is insufficient.
4. Pin newline handling for every byte-hashed text artifact. Verify exact bytes in
   a Windows checkout and a Linux checkout; never rewrite a checksum to hide mutation.
5. Publish the manifest and evaluation inventory atomically with the release pointer.
   Keep at least one independent verified backup under a documented retention owner.
   Do not delete the source checkpoint until remote retrieval and backup checks pass.
6. Promotion fails closed if any required artifact, revision, identity proof, test,
   citation/verifier safety gate or retrieval check is missing. System promotion and
   weight promotion are separate decisions.

## Recovery and incidents

Preserve original files, hashes, logs and repository state before repairs. Classify
recovery as `EXACT_RECOVERY`, `PROBABLE_RECOVERY`, or `NOT_RECOVERED` and state the
evidence and its limits. A newly calculated hash cannot establish historical identity.
Never regenerate weights and label them as a lost historical release. A replacement
release would require a separately authorized version and complete new provenance.

The T9 incident demonstrates three independent failure modes: ignored production
weights, checkout newline conversion, and T8S commits left in another local repository.
Release review must verify the pushed commit, remote artifacts and exact test inventory,
not only the developer workspace.
