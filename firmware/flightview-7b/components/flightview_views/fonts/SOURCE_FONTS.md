# FlightView 7B font sources

The generated LVGL fonts in this directory are built from bundled static TTFs
from the official public font repositories below. The TTFs are retained so the
generated C assets can be reproduced without relying on mutable remote files.

## Outfit

- Repository: <https://github.com/Outfitio/Outfit-Fonts>
- Commit: `902773808eb372f70fb34e8946dd1ffe604efc79`
- Source files:
  - `fonts/ttf/Outfit-ExtraBold.ttf`
  - `fonts/ttf/Outfit-Bold.ttf`
- License: SIL Open Font License 1.1, copied at `licenses/Outfit-OFL.txt`
- Source hashes:
  - `source_ttf/Outfit-ExtraBold.ttf`: `0f028cbdc61a588bc44fef911e8d2bcfc0bc05b241a9b797686024d269d964b6`
  - `source_ttf/Outfit-Bold.ttf`: `f620b69582e06d7e1b3bbde74ed8c5876eadabb038390780db2a3414a1490197`

## JetBrains Mono

- Repository: <https://github.com/JetBrains/JetBrainsMono>
- Commit: `19371302b95d218af43299bce79ddbddd0bc364d`
- Source file: `fonts/ttf/JetBrainsMono-Bold.ttf`
- License: SIL Open Font License 1.1, copied at `licenses/JetBrainsMono-OFL.txt`
- Source hash:
  - `source_ttf/JetBrainsMono-Bold.ttf`: `d22c4f3821d725eb01210d278d95dfcfcaadc34699a06658d47c8a5cc5830ada`

## Generated coverage

- Outfit assets include ASCII printable characters plus the Latin-1 Supplement
  (`U+0020-U+007E`, `U+00A0-U+00FF`) for carrier names, cities, full aircraft
  names, and secondary header text. The generator explicitly checks city samples
  `São Paulo` and `München` for `fv_outfit_28`.
- JetBrains Mono assets include ASCII printable characters plus the degree sign
  (`U+0020-U+007E`, `U+00B0`) for type codes, IATA route endpoints, and stats.
