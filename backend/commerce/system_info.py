"""Validate device-supplied information; never use it for access decisions."""
from django.core.exceptions import ValidationError

def sanitize(value):
    if not isinstance(value, dict): raise ValidationError('Invalid system information.')
    result = {}
    for field in ['os', 'version', 'arch', 'cpu']:
        if not isinstance(value.get(field), str) or len(value[field]) > 200: raise ValidationError('Invalid system information.')
        result[field] = value[field]
    for field, maximum in [('cores', 4096), ('ram_bytes', 2**55)]:
        if type(value.get(field)) is not int or not 0 <= value[field] <= maximum: raise ValidationError('Invalid system information.')
        result[field] = value[field]
    disks = value.get('disks', [])
    if not isinstance(disks, list) or len(disks) > 16: raise ValidationError('Invalid disk information.')
    result['disks'] = []
    for disk in disks:
        if not isinstance(disk, dict) or not isinstance(disk.get('name'), str) or len(disk['name']) > 80: raise ValidationError('Invalid disk information.')
        if any(type(disk.get(k)) is not int or not 0 <= disk[k] <= 2**55 for k in ['total_bytes', 'free_bytes']): raise ValidationError('Invalid disk information.')
        if disk['free_bytes'] > disk['total_bytes']: raise ValidationError('Invalid disk information.')
        result['disks'].append({k: disk[k] for k in ['name', 'total_bytes', 'free_bytes']})
    return result
