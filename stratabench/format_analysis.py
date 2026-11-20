"""Explain narrowly verifiable representation mistakes without changing strict grades."""
import json
import re

from .grading import extract_answer, exact, numeric


def inspect(case, row):
    if row.get('correct') is not False or row.get('error') or row.get('truncated') or row.get('standard_result'):
        return None
    answer, _ = extract_answer(row.get('content',''))
    expected = case.get('answer');kind=case.get('grader')
    reason=None;normalized=None
    if case.get('group')=='bbh_word_sorting' and isinstance(expected,str):
        if isinstance(answer,list) and answer and all(isinstance(x,str) and re.fullmatch(r'\S+',x) for x in answer):
            normalized=' '.join(answer)
            if exact(normalized)==exact(expected):reason='The words and their order match exactly, but the answer is a JSON array instead of the required space-separated string.'
        elif answer is None:
            text=row.get('content','').strip()
            if '</think>' in text:text=text.rsplit('</think>',1)[1].strip()
            elif '<think>' in text:return None
            words=[re.sub(r'^(?:[-*]\s+|\d+[.)]\s+)', '',line.strip()) for line in text.splitlines() if line.strip()]
            if len(words)>1 and all(re.fullmatch(r'\S+',word) for word in words):
                normalized=' '.join(words)
                if exact(normalized)==exact(expected):reason='The words and their order match exactly, but they are written as separate list lines instead of a space-separated answer.'
    elif kind in ('numeric','choice') and isinstance(answer,list) and len(answer)==1:
        normalized=answer[0]
        if kind=='numeric' and numeric(normalized) is not None and numeric(normalized)==numeric(expected):
            reason='The numeric value matches, but a one-item array was returned instead of a number or numeric string.'
        elif kind=='choice' and isinstance(normalized,str) and exact(normalized).strip('(). ')==exact(expected).strip('(). '):
            reason='The option label matches, but a one-item array was returned instead of the label.'
    elif kind=='json' and isinstance(answer,str) and isinstance(expected,(dict,list)):
        try:
            normalized=json.loads(answer)
            if json.dumps(normalized,sort_keys=True,ensure_ascii=False)==json.dumps(expected,sort_keys=True,ensure_ascii=False):
                reason='The structure matches after decoding, but it was returned as a JSON-encoded string instead of the requested object or array.'
        except (ValueError,RecursionError):pass
    return {'reason':reason,'normalized':normalized,'strict_correct':False,'diagnostic_only':True} if reason else None
