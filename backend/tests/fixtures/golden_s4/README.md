# Golden S4 corpus

This corpus characterizes the deterministic OpenAPI inspector, diff, checks, and
`SpecChangeEngine` using 15 small document pairs. Each scenario contains
`old.json`, `new.json`, and frozen outputs in `expected/`. The `yaml_variant`
scenario intentionally stores YAML text in `new.json`, so the loader exercises
the tools' YAML string support while keeping the required pair filenames.

The four checks applied to each new document are fixed in `_regen.py`:
security, required 400/401 responses, kebab path naming, and operation ID
uniqueness/presence. The spec change result includes generated proposal text,
findings for confirmed proposals, and a confirmed unrelated requirement (or a
confirmed requirement against the invalid document).

Regenerate all scenario documents and expected outputs from `backend` with:

```powershell
& 'D:\CAP1_AI_STUDIO_C1SE27\backend\.venv\Scripts\python.exe' tests\fixtures\golden_s4\_regen.py
```

The helper uses only local deterministic inputs and writes JSON with sorted keys.
The separate content-type assertion is marked xfail because the current diff
does not report a request body media-type-only change; the frozen output still
records the current behavior, and the check result records disallowed media.
