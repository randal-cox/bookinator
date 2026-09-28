const [list, search, type, status, count] = ["list","search","type","status","count"].map((id) => document.getElementById(id));
const configured = document.querySelector('meta[name="bookinator-app-url"]')?.content.trim();
document.getElementById("app-destination").href = configured ? new URL(configured, location.href) : new URL("../../", location.href);
// Resource copy changes more often than the shell. Do not let an old browser
// cache make retired claims linger in the catalog after the JSON is updated.
const response = await fetch("catalog.json", { cache: "no-store" });
if (!response.ok) throw new Error(`Could not load resource catalog: ${response.status}`);
const resources = await response.json();
const addOptions = (select, values) => select.append(...[...new Set(values)].sort().map((value) => Object.assign(document.createElement("option"), { value, textContent: value })));
addOptions(type, resources.map((r) => r.type)); addOptions(status, resources.map((r) => r.status));
const cardFor = (resource) => {
  const card = document.createElement("article"); card.className = "card";
  card.innerHTML = `<div><div class="meta"></div><h2></h2><p></p><div class="tags"></div></div><nav class="actions"></nav>`;
  card.querySelector(".meta").textContent = `${resource.type} · ${resource.status}`;
  card.querySelector("h2").textContent = resource.title; card.querySelector("p").textContent = resource.description;
  card.querySelector(".tags").append(...resource.tags.map((tag) => Object.assign(document.createElement("span"), { textContent: tag })));
  card.querySelector(".actions").append(...resource.actions.map((action) => Object.assign(document.createElement("a"), { href: action.url, textContent: action.label, className: action.primary ? "primary" : "" })));
  return card;
};
const render = () => { const q = search.value.trim().toLowerCase(); const visible = resources.filter((r) => (!q || JSON.stringify(r).toLowerCase().includes(q)) && (!type.value || r.type === type.value) && (!status.value || r.status === status.value)); count.textContent = `${visible.length} of ${resources.length} resources`; list.replaceChildren(...visible.map(cardFor)); };
[search,type,status].forEach((control) => control.addEventListener("input", render)); render();
