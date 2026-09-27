"""Stable question metadata and authoritative answer cardinality."""
import copy
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from .backend_contract import error

MAX_QUERY_DAYS=31
RECENT_DAYS=(7,15,31)
TIME_QUESTION=re.compile(r'时间|时段|日期|期间')
DIGITS={'零':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
UNIT_DAYS={'天':1,'日':1,'周':7,'星期':7,'个月':30,'月':30,'季度':90,'年':365}
RELATIVE=re.compile(r'(?:近|最近|过去|前)\s*([0-9]+|[零一二两三四五六七八九十]+|半)?\s*(个月|季度|星期|天|日|周|月|年)')
DATE=re.compile(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?(?:\s*(\d{1,2}):(\d{2})(?::(\d{2}))?)?')


def _number(text):
    if text is None:return 1
    if text=='半':return 0.5
    if text.isdigit():return int(text)
    if '十' in text:
        tens,_,units=text.partition('十')
        return (DIGITS.get(tens,1) if tens else 1)*10+(DIGITS.get(units,0) if units else 0)
    return DIGITS.get(text)


def label_span_days(label):
    """Span in days a time option label covers, or None when it cannot be read."""
    if not isinstance(label,str):return None
    dates=DATE.findall(label)
    if len(dates)>=2:
        try:
            left,right=(datetime(int(y),int(m),int(d),int(h or 0),int(mi or 0),int(s or 0)) for y,m,d,h,mi,s in dates[:2])
        except ValueError:return None
        return (right-left).total_seconds()/86400
    if re.search(r'半年',label):return 182
    match=RELATIVE.search(label)
    if not match:return None
    count=_number(match.group(1))
    return None if count is None else count*UNIT_DAYS[match.group(2)]


def recent_options(today=None):
    today=today or date.today()
    end=today.strftime('%Y-%m-%d')+' 23:59:59'
    return [{'label':f"近{days}天（{(today-timedelta(days=days-1)).strftime('%Y-%m-%d')} 00:00:00 至 {end}）",'description':''} for days in RECENT_DAYS]


def limit_time_options(questions, today=None):
    """Drop time options longer than one query may span; readable labels only."""
    for q in questions:
        if not isinstance(q,dict) or not isinstance(q.get('options'),list) or not q['options']:continue
        if not TIME_QUESTION.search(str(q.get('header',''))+str(q.get('question',''))):continue
        kept=[o for o in q['options'] if not isinstance(o,dict) or (label_span_days(o.get('label')) or 0)<=MAX_QUERY_DAYS]
        q['options']=kept or recent_options(today)
    return questions


def project(item):
    questions=limit_time_options(copy.deepcopy(item.get('questions', [])))
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
