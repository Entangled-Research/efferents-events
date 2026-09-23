"""Execute dashboard rendering against a tiny DOM stub to check ownership semantics."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

JS = (Path(__file__).resolve().parents[1] / "efferents/dashboard/static/dashboard.js").read_text()
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is needed for dashboard JavaScript checks")


def run_js(assertions):
    stub = """
const elements = new Map();
globalThis.window = {location:{hash:'#network'}};
globalThis.localStorage = {getItem:()=>null,setItem:()=>{}};
globalThis.document = {
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, {textContent:'',innerHTML:'',style:{},hidden:false});
    return elements.get(id);
  },
  querySelectorAll:()=>[]
};
"""
    # Skip only the entrypoint; the real functions and state are evaluated intact.
    source = JS.rsplit("\ninitRouting();", 1)[0]
    result = subprocess.run([NODE, "-"], input=stub + source + assertions,
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_budget_always_belongs_to_signed_in_user_and_lab_spend_has_no_cap():
    result = run_js("""
controlState.mode = 'cluster';
controlState.connected = true;
portfolioState.labs = [
 {lab_id:'mine',budget:{spent:3,cap:999}},
 {lab_id:'other',budget:{spent:700,cap:1000}}
];
renderSession({cluster:{joined:true,owner:{name:'ChemistryNerd'},
 owner_budget:{spent_usd:7.25,cap_usd:50},proxy_spend_usd:5,proxy_cap_usd:10}});
renderBudget();
const network = document.getElementById('budget').textContent;
window.location.hash = '#observe/other';
selectedLabId = 'other';
renderBudget();
console.log(JSON.stringify({network, observer:document.getElementById('budget').textContent,
 selected:document.getElementById('selected-lab-spend').textContent,
 lab:labSpendMarkup(portfolioState.labs[1])}));
""")
    assert result["network"] == "your total spend · $7.25 / $50.00"
    assert result["observer"] == result["network"]
    assert result["selected"] == "this lab · $700.00"
    assert "$700.00" in result["lab"]
    assert "$1000" not in result["lab"]
    assert "progressbar" not in result["lab"]


def test_each_idea_links_to_its_own_evaluation_and_escapes_content():
    result = run_js("""
const lab = {lab_id:'chem',display_name:'Chemistry',ideas:[
 {id:'mechanism',name:'Rare mechanisms',verdict:'undecided'},
 {id:'<other>',name:'<script>alert(1)</script>',verdict:'falsified'}
]};
portfolioState.labs = [lab];
console.log(JSON.stringify(ideaBranchMarkup(lab)));
""")
    assert 'href="#observe/chem/idea/mechanism"' in result
    assert 'href="#observe/chem/idea/%3Cother%3E"' in result
    assert "Ideas · 2" in result
    assert "<script>" not in result
    assert "&lt;script&gt;" in result
    assert 'lab-idea-branch falsified' in result


def test_budget_holds_are_separate_from_spend_and_clear_on_account_change():
    result = run_js("""
controlState.mode = 'cluster';
renderSession({cluster:{joined:true,owner:{name:'Ada'},
 owner_budget:{spent_usd:7.25,cap_usd:50,reserved_usd:2,remaining_usd:40.75}}});
renderBudget();
const held = {spend:document.getElementById('budget').textContent,
 text:document.getElementById('budget-reserved').textContent,
 hidden:document.getElementById('budget-reserved').hidden};
renderSession({cluster:{joined:true,owner:{name:'Grace'},
 owner_budget:{spent_usd:1,cap_usd:50,reserved_usd:0,remaining_usd:49}}});
renderBudget();
console.log(JSON.stringify({held,cleared:document.getElementById('budget-reserved').hidden,
 text:document.getElementById('budget-reserved').textContent}));
""")
    assert result["held"] == {"spend": "your total spend · $7.25 / $50.00",
                              "text": "$2.00 reserved · $40.75 available", "hidden": False}
    assert result["cleared"] and result["text"] == ""


def test_receipt_alone_never_claims_experimental_use():
    result = run_js("""
const publication = {id:'paper1',kind:'publication',publication_status:'accepted',lab_id:'physics',journal:'Physics'};
portfolioState.labs = [{lab_id:'physics',journal:'Physics'}, {lab_id:'chem',journal:'Chemistry'}];
portfolioState.findings = [publication];
portfolioState.observations = [{finding_id:'paper1',target:'chem',source:'physics'}];
const receiptOnly = publicationUseMarkup(publication);
portfolioState.journal_uses = [{finding_id:'paper1',source:'physics',target:'chem',
 local_campaign_id:'rare-mechanisms',run_ids:['chem-run-1'],use_kind:'method_or_design',
 reproduction_status:'not_verified',why:'Compare a calibration method'}];
const used = publicationUseMarkup(publication);
portfolioState.journal_uses.push({finding_id:'unaccepted',source:'physics',target:'chem'});
console.log(JSON.stringify({receiptOnly,used,count:journalUses().length}));
""")
    assert result["receiptOnly"] == ""
    assert "cross-domain" in result["used"]
    assert "reproduction not verified" in result["used"]
    assert "chem-run-1" in result["used"]
    assert "rare-mechanisms" in result["used"]
    assert result["count"] == 1


def test_remote_steering_log_distinguishes_queued_and_delivered_commands():
    result = run_js("""
renderSteering([
 {ts:'2026-09-23T22:00:00Z',text:'Keep prior evidence',action:'steer',by:'participant:Ada',ack:null},
 {ts:'2026-09-23T22:01:00Z',text:'Pause safely',action:'pause',by:'participant:Ada',ack:'2026-09-23T22:02:00Z'}
]);
console.log(JSON.stringify(document.getElementById('steering-history').innerHTML));
""")
    assert "Keep prior evidence" in result
    assert "Pause safely" in result
    assert " · queued" in result
    assert " · delivered" in result
    assert "2026-09-23 22:00" in result
