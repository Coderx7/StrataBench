"""The effective system messages for each model request and prompt experiment."""
import copy

SYSTEM = ('Solve the task accurately. You may reason before answering. End with a JSON object '
          'with exactly one key, "answer", containing your final answer. For a multiple-choice '
          'question use only the option label; for a numeric question use a number or a numeric '
          'string; for a structured answer use the requested object or list as the answer value. '
          'Do not include an explanation inside the answer value.')
SWE_SYSTEM = 'You fix software issues in a Linux repository at /testbed. Use the terminal tool to inspect files, edit the code, and run tests. Changes stay inside this task container. Do not modify tests to hide failures. Finish with a short summary after implementing the fix.'


def messages(case):
    if case.get('standard_suite') == 'bfcl':
        result = copy.deepcopy(case['messages'])
    else:
        system = SWE_SYSTEM if case.get('standard_suite') == 'swebench' else case.get('system', SYSTEM)
        has_system = case.get('standard_suite') == 'swebench' or not (case.get('standard_suite') and case.get('system') is None)
        result = ([{'role':'system','content':system}] if has_system else []) + [{'role':'user','content':case['prompt']}]
    if 'system_override' in case:
        result = [m for m in result if m['role'] != 'system']
        if case['system_override']:
            result.insert(0, {'role':'system','content':case['system_override']})
    return result


def system_messages(case, request=None):
    source = request['messages'] if request and 'messages' in request else messages(case)
    return [copy.deepcopy(m) for m in source if m.get('role') in ('system','developer')]


def system_text(case, request=None):
    return '\n\n'.join(str(m.get('content','')) for m in system_messages(case,request))
