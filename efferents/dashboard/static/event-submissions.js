// Event contributions are human proposals. No results or credentials cross labs.
(() => {
  const form = document.getElementById("research-submission-form");
  const input = document.getElementById("research-question");
  const destination = document.getElementById("research-destination");
  const status = document.getElementById("research-submission-status");
  const copy = document.getElementById("research-copy-setup");
  let requestId = null, submittedText = null, receipt = null, activeOwner = null;
  function saveDraft() {
    if (activeOwner) writeStored(`efferents-research-draft:${activeOwner}`, {
      text: input.value, destination: destination.value, requestId, submittedText,
    });
  }
  function showReceipt(item) {
    receipt = item;
    copy.hidden = item.action !== "create";
    status.textContent = item.needs_refinement
      ? "Objective saved. Copy setup instruction; your coding agent will refine its ideas and evaluator."
      : item.action === "append"
      ? `Idea queued for ${item.lab_id} · ${item.journal}. ${item.requires_upgrade ? "Its resource custodian must update the existing workspace to receive contributions." : "It will be added at the next heartbeat."} The lab keeps its existing budget and pause state.`
      : item.action === "create"
      ? `${item.objective} · ${item.journal} · ${item.ideas.length} proposed idea${item.ideas.length === 1 ? "" : "s"}. Copy setup instruction to build this lab on your computer.`
      : "Objective saved. Submit again to retrieve or retry routing.";
  }
  function restoreReceipt(item) {
    input.value = item.text;
    requestId = item.request_id || null;
    const target = item.preferred_lab ? `lab:${item.preferred_lab}` : item.preferred_journal ? `journal:${item.preferred_journal}` : "";
    destination.value = target;
    submittedText = JSON.stringify([item.text, destination.value]);
    saveDraft();
    showReceipt(item);
  }
  async function savedSubmissions() {
    const owner = activeOwner;
    if (!owner) return;
    try {
      const items = await getJSON("/api/network/submissions");
      if (activeOwner !== owner) return;
      const box = document.getElementById("research-saved-submissions");
      box.replaceChildren();
      for (const item of items) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "compact-button";
        button.textContent = `${item.objective || item.text.slice(0, 65)} · saved`;
        button.addEventListener("click", () => restoreReceipt(item));
        box.appendChild(button);
      }
      if (!input.value.trim() && items.length) restoreReceipt(items[0]);
      else if (requestId) {
        const matching = items.find(item => item.request_id === requestId && item.text === input.value.trim());
        if (matching) showReceipt(matching);
      }
    } catch (_) { /* Preserve the current local draft when reconnecting. */ }
  }
  document.addEventListener("efferents-session", event => {
    const owner = event.detail.ownerId;
    if (owner === activeOwner) return;
    if (activeOwner) { saveDraft(); input.value = ""; }
    requestId = null; submittedText = null; receipt = null;
    activeOwner = owner;
    copy.hidden = true;
    status.textContent = "";
    document.getElementById("research-saved-submissions").replaceChildren();
    if (!owner) { input.value = ""; requestId = null; submittedText = null; return; }
    const draft = readStored(`efferents-research-draft:${owner}`, null);
    // Keep text entered while the initial authentication check was loading.
    if (draft) {
      input.value = draft.text || "";
      requestId = draft.requestId;
      submittedText = draft.submittedText;
    }
    void destinations().then(() => {
      if (activeOwner !== owner) return;
      if (draft?.destination) destination.value = draft.destination;
      void savedSubmissions();
    });
  });
  function changedDraft() {
    receipt = null;
    copy.hidden = true;
    status.textContent = "";
    saveDraft();
  }
  input.addEventListener("input", changedDraft);
  destination.addEventListener("change", changedDraft);
  async function destinations() {
    if (!isCluster() || !isJoined()) return;
    try {
      const payload = await getJSON("/api/labs");
      const selected = destination.value;
      destination.replaceChildren(new Option("Find a lab or journal automatically", ""));
      const journals = new Set();
      for (const lab of payload.labs || []) {
        destination.add(new Option(`Lab · ${lab.display_name || lab.lab_id}`, `lab:${lab.lab_id}`));
        if (lab.journal) journals.add(lab.journal);
      }
      for (const journal of journals) destination.add(new Option(`Journal · ${journal}`, `journal:${journal}`));
      destination.value = selected;
    } catch (_) { /* Automatic routing remains available. */ }
  }
  destination.addEventListener("focus", destinations);
  window.addEventListener("hashchange", destinations);
  document.querySelectorAll("[data-research-example]").forEach(button => {
    button.addEventListener("click", () => { input.value = button.dataset.researchExample; changedDraft(); input.focus(); });
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const button = document.getElementById("research-submit");
    if (button.disabled) return;
    if (receipt && receipt.text === input.value.trim() && ["append", "create"].includes(receipt.action)
        && submittedText === JSON.stringify([input.value.trim(), destination.value])) {
      showReceipt(receipt);
      return;
    }
    button.disabled = true;
    copy.hidden = true;
    status.textContent = "Finding the research team…";
    const value = input.value.trim();
    const signature = JSON.stringify([value, destination.value]);
    if (!requestId || signature !== submittedText) { requestId = crypto.randomUUID(); submittedText = signature; }
    saveDraft();
    try {
      const target = destination.value;
      receipt = await postJSON("/api/network/submissions", {text: value, request_id: requestId,
        lab_id: target.startsWith("lab:") ? target.slice(4) : null,
        journal: target.startsWith("journal:") ? target.slice(8) : null});
      showReceipt(receipt);
      await savedSubmissions();
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(fundedSetupCommand(controlState.session, null, receipt.id));
      status.textContent = "Copied. Paste into your coding agent’s chat.";
    } catch (error) { status.textContent = error.message; }
  });
})();
