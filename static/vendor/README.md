# Libraries SGXray serves itself

Only the home page's 3D scene uses these. They used to load from jsDelivr, an outside site, with no check that
the code hadn't been changed (audit 4, 25 Nov 2026). Now SGXray serves them, so no outside site sees visitors'
network addresses or can swap the code, and the Content Security Policy allows scripts from SGXray only.

| Library | Version | Source | Package sha512 (checked against the npm registry) | Licence |
|---|---|---|---|---|
| three.js | 0.186.1 | npm `three@0.186.1` | `sha512-blFeqb49wRCSGUGj7gtpfnSGHy2lwDk94RhUmS1c/hTby70kvChbWpkJ4Pm1390LqzzvTmzgXKHPEafJwCb8jA==` | MIT (`three-0.186.1/LICENSE`) |
| Lenis | 1.3.26 | npm `lenis@1.3.26` | `sha512-s/xTCZCxTFvHbAN1OzuhNaN5YPJH2ail0XAkctKW1b+RUAG4nUL5UHLXwNko1h8aEeT2jspBXegMgPJd8zcuag==` | MIT (`lenis-1.3.26/LICENSE`) |

Only the files the page imports were copied, unchanged. Each file's own fingerprint, so a changed file is spotted
(`tests/test_vendor.py` checks them):

| File | Bytes | sha256 |
|---|---|---|
| `lenis-1.3.26/lenis.css` | 513 | `2f668ae84a668327f246faf8a770383a2bf69196d214290fbc4d5548910606c5` |
| `lenis-1.3.26/lenis.min.js` | 18,722 | `53195c9797e7ce7bf9d7fa9242b08209e57f46de4c9dac126a6494fa780e3346` |
| `lenis-1.3.26/LICENSE` | 1,096 | `bba15b1137346a73ed8c35e7f20961a69e0ed842d956a50339240c3e7b08c089` |
| `three-0.186.1/build/three.core.js` | 1,458,113 | `9edde002b066a9a05676a6127f67735b62baf399bdea529f2f7e31657da769e6` |
| `three-0.186.1/build/three.module.js` | 662,772 | `9052042d676cb0fdc1ddfefe193053f34b7ac0513a616fdac4535d49987812ea` |
| `three-0.186.1/examples/jsm/lines/Line2.js` | 1,486 | `69dd2120d4df14208796acf199f80a64d37e042cfa65dc2b98286694b2954194` |
| `three-0.186.1/examples/jsm/lines/LineGeometry.js` | 3,479 | `b7ec6b0011e3b09dc72e17cfd8e8945295cb2bc8c8aa9aa19e47119680bdad7e` |
| `three-0.186.1/examples/jsm/lines/LineMaterial.js` | 14,020 | `d4517001f9d7b3e885ea5baa930de0077351e885db52ef4565cde4c7dd17eb23` |
| `three-0.186.1/examples/jsm/lines/LineSegments2.js` | 11,477 | `fcbc20f576e88343cea12131f49b7003d7ab44ede422fcb694e567456022f7a0` |
| `three-0.186.1/examples/jsm/lines/LineSegmentsGeometry.js` | 6,893 | `471f0a954a0c9c59d3d151392f424142a9164a722802f63b371971378a84a1b1` |
| `three-0.186.1/LICENSE` | 1,081 | `8b378ebe60e2fe500158cb0ac71cb5e8b7d92953c2abcc63a0eb90499653b5bc` |

**To update one:** `npm pack <name>@<version>` in an empty folder (npm checks the registry's sha512 as it downloads),
copy the same files across, update the versions in `templates/home.html` and both tables here, then run the tests.
