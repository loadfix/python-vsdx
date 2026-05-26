# ShapeSheet formula coverage

`vsdx.formula` ships a hand-rolled parser + evaluator for Visio's
ShapeSheet formula language so library-only tooling (preview, validate,
convert without Visio) can resolve `Cell/@F` expressions like `Width*0`,
`(BeginX+EndX)/2`, and `ATAN2(EndY-BeginY, EndX-BeginX)` without booting
Visio desktop.

The reference for canonical names is the
[Visio Functions Reference on MS Learn](https://learn.microsoft.com/en-us/office/client-developer/visio/functions-reference).
What follows is the loadfix subset.

## Operators

| Operator         | Meaning                                                |
|------------------|--------------------------------------------------------|
| `+ - * /`        | Numeric add / subtract / multiply / divide             |
| `^`              | Exponent (right-associative)                           |
| Unary `+` / `-`  | Identity / negation                                    |
| `&`              | String concatenation                                   |
| `= <> < <= > >=` | Comparison; result is a boolean                        |

Type rules match Visio / Excel: numbers and booleans coerce freely (TRUE
becomes 1.0); strings coerce to numbers when they parse, otherwise
raise `FormulaTypeError` from a numeric op. Comparisons fall back to
string ordering when either side is a string.

`/0` raises `FormulaEvaluationError("division by zero")`. `SQRT(-x)`,
`LN(0)`, `ASIN/ACOS` outside `[-1, 1]`, `MOD(_, 0)`, and
`CEILING/FLOOR(_, 0)` all raise structured `FormulaEvaluationError`s
rather than returning Python's `inf` / `nan`.

## Built-in functions

### Math / trig

| Visio name | Python equivalent                         | Notes                                                     |
|------------|-------------------------------------------|-----------------------------------------------------------|
| `ABS`      | `abs`                                     |                                                           |
| `SIGN`     | `1 / -1 / 0`                              | Returns float for parity with the other helpers.          |
| `SQRT`     | `math.sqrt`                               | Negative input raises `FormulaEvaluationError`.           |
| `SIN`      | `math.sin`                                | Argument in radians.                                      |
| `COS`      | `math.cos`                                |                                                           |
| `TAN`      | `math.tan`                                |                                                           |
| `ASIN`     | `math.asin`                               | Domain-checked.                                           |
| `ACOS`     | `math.acos`                               | Domain-checked.                                           |
| `ATAN`     | `math.atan`                               |                                                           |
| `ATAN2`    | `math.atan2(y, x)`                        | Visio order: `(y, x)` like Excel.                         |
| `DEGREES`  | `math.degrees`                            |                                                           |
| `RADIANS`  | `math.radians`                            |                                                           |
| `EXP`      | `math.exp`                                |                                                           |
| `LN`       | `math.log`                                | `LN(0)` and negative input raise.                         |
| `LOG10`    | `math.log10`                              |                                                           |
| `POWER`    | `math.pow(base, exp)`                     | Same as the `^` operator with explicit arity.             |
| `MOD`      | `math.fmod(a, b)`                         | Sign of result matches dividend (Visio convention).       |
| `INT`      | `math.floor`                              | Visio's `INT` rounds toward `-∞`, not toward zero.        |
| `TRUNC`    | `math.trunc(x * 10**d) / 10**d`           | `digits` defaults to 0.                                   |
| `ROUND`    | `round`                                   | Banker's rounding (CPython's default).                    |
| `CEILING`  | `ceil(x / m) * m`                         | `multiple` defaults to 1.                                 |
| `FLOOR`    | `floor(x / m) * m`                        | `multiple` defaults to 1.                                 |
| `PI`       | `math.pi`                                 | Zero-arity.                                               |

### Statistics / selection

| Visio name | Python equivalent           | Notes                                                  |
|------------|-----------------------------|--------------------------------------------------------|
| `MIN`      | `min`                       | Variadic; raises on empty input (Visio matches).       |
| `MAX`      | `max`                       | Variadic.                                              |
| `SUM`      | `math.fsum`                 | Variadic, zero-arg returns 0.                          |
| `AVG`      | `mean`                      | Variadic.                                              |
| `AVERAGE`  | alias of `AVG`              |                                                        |
| `COUNT`    | counts numerics             | Strings and `None` are skipped (Excel/Visio rule).     |

### Logical

| Visio name | Python equivalent                  | Notes                                                  |
|------------|------------------------------------|--------------------------------------------------------|
| `IF`       | conditional expression             | Short-circuits — only the chosen branch is evaluated.  |
| `AND`      | `all` over `_to_bool`              | Short-circuits at first falsy arg.                     |
| `OR`       | `any` over `_to_bool`              | Short-circuits at first truthy arg.                    |
| `NOT`      | `not`                              |                                                        |
| `XOR`      | parity of truthy args              | Variadic; matches Excel's behaviour.                   |
| `TRUE`     | `True`                             | Zero-arity function form (also a literal).             |
| `FALSE`    | `False`                            |                                                        |
| `ISERR`    | always `False`                     | We don't propagate Visio error sentinels.              |
| `ISERROR`  | alias of `ISERR`                   |                                                        |

### Lookup / indirection

| Visio name | Python equivalent          | Notes                                                  |
|------------|----------------------------|--------------------------------------------------------|
| `INDEX`    | tuple index                | 0-based, clamped to range.                             |
| `LOOKUP`   | walk key/value pairs       | First key match wins; returns `None` on miss.          |
| `USE`      | named-cell lookup          | Probes the live `ShapeSheetContext`; passthrough else. |
| `SUMIF`    | scalar conditional sum     | Conditions like `">5"`, `"<=10"`, `"<>0"` honoured.    |

### String

| Visio name    | Python equivalent             | Notes                                              |
|---------------|-------------------------------|----------------------------------------------------|
| `LEN`         | `len`                         | Returns float to keep numeric-context consistency. |
| `LEFT`        | `s[:n]`                       |                                                    |
| `RIGHT`       | `s[-n:]`                      | `n=0` returns empty string.                        |
| `MID`         | `s[i-1:i-1+k]`                | 1-based start index (Visio convention).            |
| `UPPER`       | `str.upper`                   |                                                    |
| `LOWER`       | `str.lower`                   |                                                    |
| `TRIM`        | `str.strip`                   |                                                    |
| `CONCATENATE` | `"".join`                     | Variadic.                                          |
| `CONCAT`      | alias of `CONCATENATE`        | Visio 2013+ name.                                  |
| `FORMAT`      | passthrough stringification   | Picture-string parsing is deferred (TODO).         |
| `FORMATEX`    | passthrough stringification   | Extended-format sibling, also deferred.            |

### ShapeSheet / authoring

| Visio name      | Python equivalent          | Notes                                                  |
|-----------------|----------------------------|--------------------------------------------------------|
| `GUARD`         | identity                   | Visio marks the cell user-protected at edit time.      |
| `SETATREF`      | identity (passthrough)     | The mutation side-effect is not modelled at eval time. |
| `SETATREFEVAL`  | alias of `SETATREF`        |                                                        |
| `SETATREFEXPR`  | alias of `SETATREF`        |                                                        |
| `DEPENDSON`     | first-arg identity         | Dependency edge is recorded by the graph pass.         |
| `THEMEVAL`      | fallback or 0              | Theme-color resolution is deferred.                    |
| `BOUND`         | clamp(`x`, `lo`, `hi`)     | Auto-swaps `lo`/`hi` when reversed.                    |
| `MINMAX`        | alias of `BOUND`           |                                                        |

### Geometry passthroughs

| Visio name | Python equivalent  | Notes                                                  |
|------------|--------------------|--------------------------------------------------------|
| `WIDTH`    | identity           | When called as a function — bare `WIDTH` is a cell.    |
| `HEIGHT`   | identity           | Idem.                                                  |
| `PNT`      | tuple `(x, y)`     | Constructs a 2-D point literal.                        |
| `LOCTOPAR` | identity           | Local→parent transform; deferred.                      |
| `PARTOLOC` | identity           | Parent→local transform; deferred.                      |

## Cell references

The parser accepts every Visio cell-reference axis:

- `Width` — singleton cell on this shape.
- `User.Scale` — section-row qualified.
- `Geometry1.X1` — section + cell-name (the resolver classifies row vs.
  cell by name shape; `X1`/`Y1`/`A1`/`B1`/etc. are recognised cell
  forms).
- `Prop.Cost.Prompt` — three-axis (section, row, cell-name).
- `Sheet.5!Width` — cross-shape, by numeric `@ID`.
- `ShapeName!Width` — cross-shape, by `@NameU` / `@Name`.

The default `ShapeContext` (built via `Context.for_shape(shape)`)
resolves all of these by walking the live oxml tree of the owning page.

## Limits / hardening

- Maximum recursive-descent / AST-walk depth: **256** per parse and per
  evaluation. Crafted inputs that exceed the cap raise
  `FormulaDepthError` rather than a Python `RecursionError`.
- The function table is closed: every unknown function name raises
  `FormulaEvaluationError`. There is no fall-through to Python globals.
- Side-effecting Visio functions (`RUNADDON`, `CALLTHIS`, `DOCMD`,
  `PLAYSOUND`, `RUNMACRO`, `OPENFILE`, `HYPERLINK`) are intentionally
  *not* registered. Formulas that mention them raise on evaluation.
- The package has zero runtime dependencies beyond the Python standard
  library (`math`, `dataclasses`, `enum`, `typing`).

## Out of scope (deferred)

- **Picture-string formatting** (`FORMAT`, `FORMATEX`) — Visio's grammar
  differs from both Excel's and .NET's; the picture string is currently
  ignored and the value stringified.
- **Theme-color resolution** (`THEMEVAL`) — needs a live theme part;
  the function returns its `fallback` arg or `0` for now.
- **Geometry transforms** (`LOCTOPAR`, `PARTOLOC`, `LOCTOLOC`,
  `ANGLEALONGPATH`, `DISTTOPATH`, `POINTALONGPATH`) — pending the
  geometry-aware pass on `vsdx.geometry`.
- **Side-effecting macros** (`RUNADDON`, `CALLTHIS`, …) — intentionally
  rejected as untrusted code.
- **Range arguments** — Visio / Excel `SUMIF(range, criterion, sum_range)`
  walks a range; the evaluator argues are scalars, so the implementation
  matches the scalar form only.
