"""Stable question metadata and authoritative answer cardinality."""
import copy
import hashlib
import json
from .backend_contract import error


def project(item):
    questions=copy.deepcopy(item.get('questions', []))
    revision=hashlib.sha256(json.dumps(questions,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    for index,q in enumerate(questions):
        q['question_id']=str(item['id'])+':'+str(index)
        q['selection_min']=1
        q['selection_max']=len(q.get('options',[]))+1 if q.get('multiple') is True else 1
        q['multiple']=q.get('multiple') is True
        q['skippable']=False
        q['skip_effect']='reject_group'
        for position,option in enumerate(q.get('options',[])):
            option['option_id']=q['question_id']+':'+revision[:12]+':'+str(position)
    return {**item,'questions':questions,'question_version':revision}


def validate(item,data):
    current=project(item)
    if data.get('question_version') not in (None,current['question_version']):
        error('question_changed','问题已更新，请刷新后重新回答。',409)
    answers=data.get('answers')
    if not isinstance(answers,list) or len(answers)!=len(current['questions']):
        error('clarification_incomplete','请回答全部问题，或跳过整组问题。',422)
    for index,(question,chosen) in enumerate(zip(current['questions'],answers)):
        field={'answers.'+str(index):'invalid_selection'}
        if not isinstance(chosen,list) or not chosen or any(not isinstance(v,str) or not v.strip() for v in chosen):
            error('clarification_incomplete','请回答全部问题，或跳过整组问题。',422,field)
        if len(chosen)>question['selection_max']:
            error('too_many_answers','此题所选答案超过允许数量。',422,field)
        if len(set(chosen))!=len(chosen):error('duplicate_answers','同一选项不能重复提交。',422,field)
        labels={o['label'] for o in question.get('options',[])}
        if question.get('custom',True) is False and any(v not in labels for v in chosen):
            error('invalid_answer','所选答案已失效，请重新选择。',422,field)
    return answers
