"""Keep measurement identity separate from presentation and reviewed resume fixes."""
from __future__ import annotations

from pathlib import Path

from .common import digest, file_hash, read_json

# These modules do not execute prompts or grade responses. Unknown modules remain
# part of the fingerprint so adding a new evaluator cannot silently bypass it.
PRESENTATION_MODULES = frozenset({
    'gui.py', 'diagnostics.py', 'estimates.py', 'reference_scores.py',
    'report.py', 'version_order.py', 'acquisition.py', 'cli.py', 'protocol.py',
})
COMPATIBILITY_FILE = Path(__file__).with_name('protocol_compatibility.json')


def code_hash(root):
    return digest({p.name: file_hash(p) for p in (Path(root)/'stratabench').glob('*.py')
                   if p.name not in PRESENTATION_MODULES})


def compatible(saved, current):
    if saved == current:
        return True
    catalog = read_json(COMPATIBILITY_FILE)
    return any(entry['current'] == current and saved in entry['previous']
               for entry in catalog['compatible_protocols'])


def signature(cases, targets, options, protocol, environment):
    return digest({'cases': cases, 'targets': targets, 'options': options,
                   'protocol': protocol, 'engine_environment': environment})


def validate_resume(manifest, cases, targets, options, environment, current_protocol):
    changed = []
    if manifest['cases_sha256'] != digest(cases):changed.append('saved questions or reference answers')
    if manifest['targets'] != targets:changed.append('Strata versions or model configurations')
    if manifest['options'] != options:
        keys = sorted(k for k in set(manifest['options']) | set(options)
                      if manifest['options'].get(k) != options.get(k))
        changed.append('run settings changed ('+', '.join(keys)+')')
    if manifest.get('environment', {}) != environment:
        keys = sorted(k for k in set(manifest.get('environment', {})) | set(environment)
                      if manifest.get('environment', {}).get(k) != environment.get(k))
        changed.append('engine environment ('+', '.join(keys)+')')
    if changed:
        raise RuntimeError('Resume refused: '+ '; '.join(changed)+
                           '. Restore the original values or start a new run.')
    expected = signature(cases, targets, options, manifest['protocol_sha256'], environment)
    if manifest['signature'] != expected:
        raise RuntimeError('Resume refused: the saved run fingerprint does not match its recorded inputs. '
                           'Restore the original run files or start a new run.')
    if not compatible(manifest['protocol_sha256'], current_protocol):
        raise RuntimeError('Resume refused: benchmark execution or scoring code changed and this update '
                           'has not been verified as compatible. Use the original StrataBench revision '
                           'or start a new run. Saved answers are unchanged.')
