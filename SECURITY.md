# Security policy

## Supported versions

Security fixes land on the current minor release. We don't backport.
If you're on an older version, the fix is "upgrade".

| Version | Supported          |
|---------|--------------------|
| 0.2.x   | yes                |
| 0.1.x   | yes                |
| < 0.1   | no — upgrade       |

## Reporting a vulnerability

Email **security@loadfix.dev** with:

- a clear description of the issue,
- a minimal reproducer if you have one,
- the version of `python-vsdx` you tested against.

Please **don't** open a public GitHub issue for security problems.

We'll acknowledge within two business days and aim to ship a fix in
the next minor release. If the issue affects dependent or sibling
projects (`python-ooxml-opc`, `python-ooxml-xmlchemy`,
`python-ooxml-docprops`) we'll coordinate the disclosure.

## Threat model summary

`python-vsdx` reads and writes the parts of a `.vsdx` OPC package.
**All of these parts are attacker-controlled XML** — every byte is
defined by the author of the document. Primary attack surface is the
XML parser itself and the per-part size before the parser runs:

- **XML External Entity (XXE).** Visio XML is parsed from user bytes.
  A naive `lxml.etree.fromstring` would follow `<!ENTITY>` declarations
  and fetch remote DTDs. All parsing in this package uses a hardened
  parser configuration: `resolve_entities=False`, `no_network=True`,
  `huge_tree=False`. No `defusedxml`-equivalent escape hatch is
  exposed on the public API.
- **Billion-laughs / entity-expansion DoS.** Entity resolution is
  disabled (`resolve_entities=False`), blocking the classic expansion
  attack before it starts. `huge_tree=False` is a belt-and-braces
  second line of defence against pathological tree shapes.
- **Zip-bomb DoS via oversized parts.** Upstream `python-ooxml-opc`
  caps the total uncompressed package size, but an attacker can still
  concentrate a bomb into a single part. Visio pages with tens of
  thousands of shapes can legitimately reach multi-MiB sizes;
  callers are expected to cap the uncompressed size of each Visio
  part before handing bytes to `vsdx.oxml.parse_xml`.
- **Cell-formula strings.** `Cell/@F` is attacker-controlled text.
  This package does **not** evaluate formulas — all formula strings
  are pass-through. No regex that could be driven into exponential
  backtracking.
- **Shape-ID reference integrity.** `Connect/@FromSheet` and
  `Connect/@ToSheet` reference shape IDs on a page. A malicious
  producer may emit dangling references; the oxml layer parses them
  as integers and does no cross-shape dereferencing — the proxy
  layer (out of 0.1.0 track-1 scope) is responsible for defensive
  lookup.
- **VBA project (`.vsdm` / `.vssm` / `.vstm`).** `python-vsdx` loads
  the `vbaProject.bin` part as an **opaque byte blob**. The bytes
  are never parsed, never executed, never decompiled. Size capped at
  16 MiB on read (see `vsdx.parts.vba.VBA_PROJECT_SIZE_CAP`). Users
  who care about macro safety must scan the blob externally (MSRT,
  oletools, Defender).
  - **VBA authoring is never in scope** for any release. Writing
    ShapeSheet / cell values + adding new shapes is well-defined;
    writing attacker-controlled VBA is not, and `python-vsdx`
    intentionally does not expose that surface.
  - Converting `.vsdm` → `.vsdx` on save-as strips the
    `vbaProject.bin` part and updates `[Content_Types].xml`. This
    is not a security feature (the underlying bytes were never
    scanned) — it is a file-format conformance guarantee.
- **Stencil + template size caps.** `.vssx` / `.vstx` and their macro
  twins can legitimately contain a large master catalogue; the
  scoping-doc §9.4 per-master / per-stencil caps (1,000 shapes per
  master, 1,000 masters per file) land in 0.2.x alongside the Tier-4
  stencil fixture.

Out of scope:

- CVEs in `lxml`, `python-ooxml-xmlchemy`, `python-ooxml-opc`,
  `typing-extensions`. Report those upstream.
- Whole-package attacks (zip parsing, `[Content_Types].xml`,
  relationship traversal). Those belong to `python-ooxml-opc`.
- Cryptographic correctness of encrypted `.vsdx` files — not
  supported in 0.1.0. Will adopt `python-ooxml-crypto` when landed.

## What counts as a security issue

**In scope:**

- A crafted Visio part causes `vsdx` to consume unbounded memory or
  CPU.
- A crafted Visio XML triggers XXE or entity expansion that escapes
  the hardened parser.
- An exception raised by `vsdx` leaks raw part content that the
  caller did not expect to appear in error output.

**Out of scope:**

- CVEs in `lxml`. The package trusts it to reject malformed XML after
  the size cap and hardened-parser-config layers.
- User's file is malformed in a way that a non-malicious writer would
  produce and we raise an error — not a security issue.
- Microsoft Visio desktop writing XML that a strict spec validator
  rejects — match Visio, not the spec (see CLAUDE.md).
