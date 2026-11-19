"""Conservative answer extraction. Never execute model output or grade hidden reasoning."""
import json
import re
from fractions import Fraction


def numeric(value):
    if isinstance(value, bool) or isinstance(value, (dict, list)) or value is None:
        return None
    s = str(value).strip().strip('$').replace('−', '-').replace('\\,', '')
    s = s.replace('\\left', '').replace('\\right', '').replace('\\dfrac', '\\frac')
    s = re.sub(r'\\(?:tfrac|frac)\{([+-]?\d+(?:\.\d+)?)\}\{([+-]?\d+(?:\.\d+)?)\}', r'(\1)/(\2)', s)
    # Grouped thousands are accepted; an arbitrary list such as 1,2 is not a number.
    if re.fullmatch(r'[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?', s):
        s = s.replace(',', '')
    s = s.replace(' ', '')
    number = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
    m = re.fullmatch(r'\(?(%s)\)?(?:/\(?(%s)\)?)?' % (number, number), s)
    if not m or len(s) > 200:
        return None
    if any(abs(int(x)) > 1000 for x in re.findall(r'[eE]([+-]?\d+)', s)):
        return None
    try:
        a = Fraction(m[1])
        return a / Fraction(m[2]) if m[2] else a
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def extract_answer(content):
    text = (content or '').strip()
    if '</think>' in text:
        text = text.rsplit('</think>', 1)[1].strip()
    elif '<think>' in text:
        return None, False
    # Decode whole objects, including fenced JSON, but never select an arbitrary number from prose.
    decoder = json.JSONDecoder()
    objects = []
    cursor = 0
    while True:
        start = text.find('{', cursor)
        if start < 0:
            break
        try:
            obj, consumed = decoder.raw_decode(text[start:])
            if isinstance(obj, dict) and 'answer' in obj:
                objects.append(obj['answer'])
            cursor = start + consumed
        except (ValueError, RecursionError):
            cursor = start + 1
    if objects:
        return objects[-1], True
    # Support ordinary math answers without demanding JSON from every version.
    boxes = []
    for match in re.finditer(r'\\boxed\{', text):
        depth, start = 1, match.end()
        for i in range(start, len(text)):
            depth += (text[i] == '{') - (text[i] == '}')
            if depth == 0:
                boxes.append(text[start:i])
                break
    if boxes:
        return boxes[-1], False
    finals = re.findall(r'(?im)^\s*(?:final(?: answer)?|answer)\s*:\s*(.+?)\s*$', text)
    if finals:
        return finals[-1].strip().strip('`'), False
    if '\n' not in text and len(text) < 300:
        return text.rstrip('.'), False
    return None, False


def exact(value):
    return re.sub(r'\s+', ' ', str(value).strip().strip('$').strip()).casefold()


def grade(case, content, finish_reason=None):
    if case['grader']=='writing':
        from .capability_cases import writing_grade
        return writing_grade(content,finish_reason,case['rules'])
    answer, formatted = extract_answer(content)
    kind, target = case['grader'], case['answer']
    correct = False
    if answer is not None:
        if kind == 'numeric':
            a, b = numeric(answer), numeric(target)
            correct = a is not None and b is not None and a == b
        elif kind == 'choice':
            correct = exact(answer).strip('(). ') == exact(target).strip('(). ')
        elif kind == 'json':
            # bool != int and string != number, even though Python sometimes compares them equal.
            correct = json.dumps(answer, sort_keys=True, ensure_ascii=False) == json.dumps(
                target, sort_keys=True, ensure_ascii=False)
        elif kind == 'exact':
            correct = exact(answer) == exact(target)
        else:
            raise ValueError('Unknown grader: ' + str(kind))
    truncated = finish_reason in ('length', 'max_tokens', 'max_output_tokens')
    # A cutoff answer is not a completed correct response, even if it contains an early answer.
    return {'correct': bool(correct and not truncated), 'extracted': answer,
            'json_format': formatted, 'unparsed': answer is None, 'truncated': truncated}
