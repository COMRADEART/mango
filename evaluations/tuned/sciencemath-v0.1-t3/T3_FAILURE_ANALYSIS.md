# T3 FAILURE ANALYSIS

*Generated:* 2026-09-03T05:20:22.900130+00:00

- Failures: 82 / 188
- Failure types: {'EXTRACTION_FAILURE': 12, 'WRONG_ANSWER': 66, 'TRUNCATED_OUTPUT': 4}
- Truncations: 16
- Extraction failures: 12
- Excessive generations (>1024 tok): 0

## Per-category detail (accuracy, failed eval_ids)

| category | n | accuracy | failed eval_ids (first 20) |
|---|---|---|---|
| algebra | 40 | 0.325 | ev1-1fda18dc7f15, ev1-2636a5bc5326, ev1-2a33e519658e, ev1-3418804a4b36, ev1-3a2cdabb3be9, ev1-435d6c8ffbc1, ev1-47a9c0841557, ev1-4c4a9c2e28b7 … |
| arithmetic | 40 | 0.775 | ev1-2062af991854, ev1-40241f3dad33, ev1-7d84b1a4cc61, ev1-8ecb9b0e629d, ev1-96582eedfd5b, ev1-c3b8420853ba, ev1-c91b537c61e4, ev1-f1a80a32e346 … |
| general_science | 60 | 0.767 | ev1-188c8dd469a6, ev1-2f115c812a70, ev1-327883371080, ev1-3a713205a9c6, ev1-649ff60bcea5, ev1-6d3c902fca8e, ev1-713cd2a8539d, ev1-9b88b79acf1e … |
| geometry | 10 | 0.200 | ev1-0054033fb1ce, ev1-2323f7825810, ev1-4fef0a98f059, ev1-5c9d65b01b71, ev1-68baaeeea611, ev1-798498945cc1, ev1-facc581a1abb, ev1-fec0def06c6e |
| instruction_following | 10 | 1.000 |  |
| probability_statistics | 10 | 0.200 | ev1-14a35fb0060d, ev1-17cff5e0d02c, ev1-63f1ef01caaa, ev1-a77d6d70b221, ev1-b5dd8e35c3d9, ev1-c6c3ec4cd761, ev1-c7fdc75c9303, ev1-f2a838435f97 |
| trigonometry_precalculus | 10 | 0.200 | ev1-0953e8219e27, ev1-2bb83dacd161, ev1-389ad3fa066c, ev1-5dd5a29852b9, ev1-89624b14b049, ev1-9ab2bf2625d8, ev1-da1877869490, ev1-e1a290a65ded |
| uncertainty_calibration | 8 | 0.000 | ev1-008c59f8e02f, ev1-52b90604fd5b, ev1-533407f65652, ev1-60b6c4e1f70a, ev1-87d4be4c7a54, ev1-af41e9abad27, ev1-b468b290ddd1, ev1-ee5e68253dcf |

## Representative examples (predictions untouched)

### wrong_answer
- `ev1-008c59f8e02f` (uncertainty_calibration): expected='__UNKNOWN__' extracted='April 12, 2023' output[:120]='Answer: \\boxed{April 12, 2023}\nThe next magnitude-9 earthquake will strike the Pacific Ring of Fire on April 12, 2023.'
- `ev1-14a35fb0060d` (probability_statistics): expected='\\frac{1}{2}' extracted='1' output[:120]='We can use the triangle inequality to find the conditions on $x$ and $y$ for a triangle to exist. The triangle inequalit'
- `ev1-17cff5e0d02c` (probability_statistics): expected='4' extracted='7' output[:120]="We can't have strawberries and pineapples together, so we have to leave out one of them. We can't have grapes and banana"

### extraction
- `ev1-0054033fb1ce` (geometry): expected='145' extracted=None output[:120]='[asy] pair A,B,C,D; A = (0,0); B = (105,0); C = (0,70); D = (0,35); draw(A--B--C--cycle); draw(A--D); label("$A$",A,SW);'
- `ev1-0953e8219e27` (trigonometry_precalculus): expected='3^{2007}' extracted=None output[:120]='We begin by noting that $a_{n+1} = a_n^3 - 3a_n^2 + 3 = (a_n - 1)^3 + 2.$\n\nWe also note that $a_{n+1} = a_n^3 - 3a_n^2 +'
- `ev1-2636a5bc5326` (algebra): expected='6' extracted=None output[:120]='We can write the largest 4-digit palindrome in base 3 as $1001_3$. We can write this number in base $b$ as $1001_b$, whi'

### truncation
- `ev1-0054033fb1ce` (geometry): expected='145' extracted=None output[:120]='[asy] pair A,B,C,D; A = (0,0); B = (105,0); C = (0,70); D = (0,35); draw(A--B--C--cycle); draw(A--D); label("$A$",A,SW);'
- `ev1-0953e8219e27` (trigonometry_precalculus): expected='3^{2007}' extracted=None output[:120]='We begin by noting that $a_{n+1} = a_n^3 - 3a_n^2 + 3 = (a_n - 1)^3 + 2.$\n\nWe also note that $a_{n+1} = a_n^3 - 3a_n^2 +'
- `ev1-2636a5bc5326` (algebra): expected='6' extracted=None output[:120]='We can write the largest 4-digit palindrome in base 3 as $1001_3$. We can write this number in base $b$ as $1001_b$, whi'
