"""Immutable release registry. Validation never accepts API paths or JSON."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
import jsonschema
from .schema import SCHEMA
from ..official_methods import BY_ID
from ..backend_contract import error

VERSION='agent-registry-v1'
ROOT=Path(__file__).with_name('profiles')

@dataclass(frozen=True)
class Profile:
    document: str
    prompt: str

    @property
    def data(self):return json.loads(self.document)
    @property
    def id(self):return self.data['id']
    @property
    def prompt_sha256(self):return hashlib.sha256(self.prompt.encode()).hexdigest()
    @property
    def profile_sha256(self):return hashlib.sha256((self.document+'\n'+self.prompt).encode()).hexdigest()
    def snapshot(self):
        data=self.data
        return {**{k:data[k] for k in ('schema_version','id','version','domain','default_scenario_id')},
                'registry_version':VERSION,'profile_sha256':self.profile_sha256,'prompt_sha256':self.prompt_sha256,
                'prompt_resource':data['prompt_file']}
    def public(self):
        return {**{k:self.data[k] for k in ('id','version','name','domain','description')},'supported_intents':list(self.data['intents']),
            'prompt_resource':self.data['prompt_file'],'prompt_sha256':self.prompt_sha256}


def load(documents,root=ROOT):
    profiles={};root=Path(root).resolve()
    for value in documents:
        jsonschema.validate(value,SCHEMA)
        if value['id'] in profiles:raise ValueError('duplicate_agent')
        domain=value['domain'];scene='DEMO-CASE-'+domain.upper()
        if value['scenario_ids']!=[scene] or value['default_scenario_id']!=scene:raise ValueError('agent_scenario_mismatch')
        if value['target_contract_profile']!=domain+'-target-v1' or value['claim_profile']!=domain+'-claims-v1':raise ValueError('agent_contract_mismatch')
        allowed={'night','companions','funds','relations','gambling'} if domain=='gambling' else {'night','companions','theft'}
        for identity in value['official_method_ids']:
            method=BY_ID.get(identity)
            if not method or method['state']!='published' or method['method'] not in allowed:raise ValueError('agent_method_not_allowed')
        for intent,definition in value['intents'].items():
            identity='peixian.method.'+definition['official_method']
            if identity not in value['official_method_ids'] or not set(definition['methods'])<=set(BY_ID[identity]['methods']):raise ValueError('agent_intent_method_mismatch')
            expected={'night_activity':['night'],'companions_check':['companions'],'funds_analysis':['funds'],'relations_check':['relations'],'vehicle_activity':['vehicles']}.get(intent,BY_ID['peixian.method.'+domain]['methods'])
            if definition['methods']!=expected:raise ValueError('agent_flow_mismatch')
            if intent=='integrated_analysis' and definition['official_method']!=domain:raise ValueError('agent_flow_mismatch')
        path=root/value['prompt_file']
        if path.is_symlink() or path.resolve().parent!=root or not path.is_file():raise ValueError('agent_prompt_path_invalid')
        prompt=path.read_text(encoding='utf-8')
        if not prompt.strip():raise ValueError('agent_prompt_empty')
        profile=Profile(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')),prompt)
        profiles[profile.id]=profile
    return MappingProxyType(profiles)

# The release manifest is explicit: no directory scan or arbitrary module loading.
PROFILES=load([json.loads((ROOT/name).read_text(encoding='utf-8')) for name in ('gambling.json','theft.json')])

def require(identity):
    if not isinstance(identity,str) or identity not in PROFILES:error('unsupported_agent','所选助手不存在或尚未开放。',422)
    return PROFILES[identity]
