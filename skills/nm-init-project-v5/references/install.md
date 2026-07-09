# Install nm-init-project-v5

## From nm-docs checkout

```bash
python3 /path/to/nm-docs/tools/nm-v5/nm_v5.py install-skill --target-dir "$HOME/.agents/skills"
# or
bash /path/to/nm-docs/tools/nm-v5/install-skill.sh --target-dir "$HOME/.agents/skills"
```

## skills CLI (ecosystem)

```bash
npx skills add notmaster/nm-docs --skill nm-init-project-v5
```

If the published layout differs, use the checkout installer above.

## After install

New agent thread:

```text
Use $nm-init-project-v5 to initialize or update this project to NM V5.
```
