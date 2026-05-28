## Project
cineCS-preview is a lightweight app to preview reconstructed CS cine images in the SAX plane from raw Bruker MRI data.

## Stack
- Python 3.10

## Structure
See NOTES.md for details on project.

## Commands
- Test: `pytest`
- Lint: `ruff check .`
- Format: `ruff format .`
- Type check: `mypy src/`

## Verification
After every change, run in this order:
1. `mypy src/` — fix type errors
2. `pytest` — fix failing tests
3. `ruff check .` — fix lint errors

## Git
- The user handles ALL git operations (staging, commits, branches, push).
  Do not run `git add`/`commit`/`push`/branch commands or offer to commit;
  read-only git inspection (`status`, `diff`, `log`) is fine.

## Don't
- Don't use `# type: ignore` without a comment explaining why.
- Don't catch bare `Exception` — catch specific exceptions.

## Keeping docs in sync
After any structural change (new file, renamed file, split/merged module, added public function), update `README.md`.