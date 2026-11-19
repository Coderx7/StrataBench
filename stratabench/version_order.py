"""Presentation order is independent of version registration and engine files."""
import re


def version_key(name):
    match = re.fullmatch(r'v?(\d+(?:\.\d+)*)(?:[-+]([A-Za-z0-9._-]+))?', name)
    if match:
        numbers = tuple(int(x) for x in match[1].split('.'))
        numbers = numbers + (0,) * max(0, 8-len(numbers))
        suffix = match[2] or ''
        return (1, numbers, not bool(suffix), tuple((0, int(p)) if p.isdigit() else (1, p.casefold())
                for p in re.findall(r'\d+|[^\d]+', suffix)), name.casefold())
    return (0, (), True, (), name.casefold())


def ordered_names(state):
    names = state.get('versions', {})
    mode = state.get('version_sort_mode', 'newest')
    sorted_names = sorted(names, key=version_key, reverse=mode != 'oldest')
    if mode != 'custom':
        return sorted_names
    saved = [name for name in state.get('version_order', []) if name in names]
    # New arrivals do not move manually arranged items. They are added in version order.
    return list(dict.fromkeys(saved)) + [name for name in sorted_names if name not in saved]


def apply_order(state, mode, order=None):
    if mode not in ('newest', 'oldest', 'custom'):
        raise ValueError('Choose Newest first, Oldest first, or Custom order.')
    if mode == 'custom':
        if not isinstance(order, list) or any(not isinstance(x, str) for x in order):
            raise ValueError('The version order must be a list of version names.')
        if len(order) != len(set(order)) or set(order) != set(state.get('versions', {})):
            raise ValueError('The version library changed. Refresh it before saving the order.')
        state['version_order'] = order
    state['version_sort_mode'] = mode
    return state
