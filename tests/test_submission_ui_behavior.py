"""Exercise the real contribution UI through refresh, retry and account changes."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

NODE=shutil.which('node')
pytestmark=pytest.mark.skipif(NODE is None,reason='Node needed')
SOURCE=(Path(__file__).resolve().parents[1]/'efferents/dashboard/static/event-submissions.js').read_text()


def run_ui(assertions):
    stub=r'''
const elements=new Map(), events={}, stored=new Map(), requests=[], copied=[];
class Element {
 constructor(){this.handlers={};this.value='';this.hidden=false;this.children=[];}
 addEventListener(name,fn){this.handlers[name]=fn;}
 replaceChildren(...items){this.children=items;}
 add(item){this.children.push(item);}
 appendChild(item){this.children.push(item);}
 focus(){}
}
for(const id of ['research-submission-form','research-question','research-destination','research-submission-status','research-copy-setup','research-submit','research-saved-submissions'])elements.set(id,new Element());
globalThis.document={getElementById:id=>elements.get(id),querySelectorAll:()=>[],createElement:()=>new Element(),addEventListener:(name,fn)=>events[name]=fn};
globalThis.window={addEventListener:()=>{}};
globalThis.Option=class {constructor(text,value){this.text=text;this.value=value;}};
globalThis.crypto={randomUUID:()=> 'stable-request-id'};
Object.defineProperty(globalThis,'navigator',{value:{clipboard:{writeText:async value=>copied.push(value)}},configurable:true});
const readStored=(key,fallback)=>stored.has(key)?stored.get(key):fallback;
const writeStored=(key,value)=>stored.set(key,value);
const isCluster=()=>true,isJoined=()=>true;
const controlState={session:{owner:{id:'A'}}};
const fundedSetupCommand=(session,intake,id)=>'setup for '+id;
let saved=[];
const getJSON=async path=>path==='/api/labs'?{labs:[]}:saved;
const postJSON=async (path,body)=>{
 requests.push(body);
 return {id:'sub_receipt',text:body.text,request_id:body.request_id,action:'create',needs_refinement:true};
};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
'''
    script=stub+SOURCE+'\n;(async()=>{\n'+assertions+'\n})().catch(e=>{console.error(e);process.exit(1)});'
    out=subprocess.run([NODE,'-'],input=script,text=True,capture_output=True,check=True)
    return json.loads(out.stdout)


def test_question_survives_refresh_and_is_scoped_to_account():
    result=run_ui('''
stored.set('efferents-research-draft:A',{text:'Keep my research question',requestId:'existing-request',submittedText:'saved'});
events['efferents-session']({detail:{ownerId:'A'}});await settle();
const input=elements.get('research-question');const first=input.value;
input.value='My edited question';input.handlers.input();
events['efferents-session']({detail:{ownerId:'A'}});await settle();
const same=input.value;
events['efferents-session']({detail:{ownerId:'B'}});await settle();
const other=input.value;
events['efferents-session']({detail:{ownerId:'A'}});await settle();
console.log(JSON.stringify({first,same,other,restored:input.value}));
''')
    assert result=={'first':'Keep my research question','same':'My edited question','other':'','restored':'My edited question'}


def test_refinement_handoff_stays_available_and_repeat_submit_is_not_recharged():
    result=run_ui('''
events['efferents-session']({detail:{ownerId:'A'}});await settle();
const input=elements.get('research-question');input.value='A precise objective';input.handlers.input();
await elements.get('research-submission-form').handlers.submit({preventDefault(){}});
await elements.get('research-submission-form').handlers.submit({preventDefault(){}});
await elements.get('research-copy-setup').handlers.click();
console.log(JSON.stringify({calls:requests.length,text:input.value,copyHidden:elements.get('research-copy-setup').hidden,copied}));
''')
    assert result=={'calls':1,'text':'A precise objective','copyHidden':False,'copied':['setup for sub_receipt']}


def test_previous_saved_receipt_is_restored_without_rerouting():
    result=run_ui('''
saved=[{id:'sub_older',text:'Existing participant input',objective:'Existing work',action:'create',ideas:[{}],journal:'Physics'}];
events['efferents-session']({detail:{ownerId:'A'}});await settle();await settle();
await elements.get('research-submission-form').handlers.submit({preventDefault(){}});
await elements.get('research-copy-setup').handlers.click();
console.log(JSON.stringify({text:elements.get('research-question').value,buttons:elements.get('research-saved-submissions').children.length,calls:requests.length,copied}));
''')
    assert result=={'text':'Existing participant input','buttons':1,'calls':0,'copied':['setup for sub_older']}
