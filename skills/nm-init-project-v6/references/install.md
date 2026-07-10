# V6 checkout and Skill installation

The Skill delegates to the repository's single deterministic CLI. It does not
download or embed another workflow implementation.

Install from a trusted local checkout:

```bash
bash tools/nm-v6/install-skill.sh --target-dir "$HOME/.agents/skills"
```

The installer records an exact mode-0600 source binding for the checkout's V6
CLI, package, tests, schemas, Spec, Skill, and template manifest. The installed
wrapper does not search the current directory or guessed home-directory paths.

If `NM_DOCS_DIR` is set later, it must equal the recorded checkout:

```bash
export NM_DOCS_DIR=/absolute/path/to/nm-docs
```

After a reviewed V6 source update or checkout move, reinstall the Skill to
refresh the binding. Digest drift fails closed; the wrapper never silently
switches to another checkout.

V6 requires Python 3.11 or newer. Set `NM_V6_PYTHON` to an approved runtime
when `python3` is older. The wrapper invokes Python in isolated mode so
`PYTHONPATH`, user-site packages, and startup customization cannot replace the
bound core. Never configure it to download unchecked code or use a mutable
remote ref without a verified digest or signature.
