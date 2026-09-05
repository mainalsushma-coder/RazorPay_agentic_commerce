const node=(tag,value,className)=>{const el=document.createElement(tag);el.textContent=value??"";if(className)el.className=className;return el};
const amount=(v,c)=>new Intl.NumberFormat("en-IN",{style:"currency",currency:c||"INR",minimumFractionDigits:2}).format(Number(v));
const timestamp=v=>v?new Date(v).toLocaleString("en-IN",{day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit",timeZoneName:"short"}):"Unavailable for this earlier session order";
const details=document.querySelector("#order-details");
function showDetails(o){
  const root=document.querySelector("#details-content");root.replaceChildren();
  root.append(node("h3",o.product_name),node("p",o.status_label,"badge"));
  if(o.status==="created")root.append(node("p","Awaiting payment. Order creation does not confirm payment completion."));
  const fields=[["Merchant",o.merchant_name],["SKU",o.sku],["Quantity",o.quantity],["Authoritative catalog price at order creation",amount(o.unit_price,o.currency)],["Total",amount(o.total,o.currency)],["Currency",o.currency],["BOUND internal order ID",o.order_id],["Razorpay order ID",o.razorpay_order_id||"Not created"],["Receipt",o.receipt||"Not created"],["Policy decision",o.policy_decision],["Purchase authority",o.authority],["Payment executor",o.payment_executor||"Not executed / unavailable"],["Created",timestamp(o.created_at)]];
  const dl=node("dl",null,"order-fields");fields.forEach(([k,v])=>dl.append(node("dt",k),node("dd",v)));root.append(dl);
  if(o.test_mode)root.append(node("p","Razorpay Test Mode","badge amber"));
  root.append(node("h3","Order activity"));
  o.audit_events.forEach(e=>root.append(node("p",`${e.label} · ${timestamp(e.timestamp)}`)));
  if(!o.audit_events.length)root.append(node("p","No linked audit events available."));
  details.showModal();
}
function orderRow(o){
  const row=node("article",null,"history-order");
  // Only local artwork is loaded; arbitrary catalog URLs cannot trigger external requests.
  const art={SKIN001:"vitamin-c-serum",SKIN002:"gentle-face-wash",SKIN003:"hydrating-moisturizer",TECH001:"wireless-keyboard",TECH002:"wireless-mouse",TECH003:"usb-c-hub"};
  const img=node("div",null,`order-art art-${art[o.sku]||"fallback"}`);img.setAttribute("role","img");img.setAttribute("aria-label",`${o.product_name} product illustration`);
  if(typeof o.image_url==="string"&&o.image_url.startsWith("/static/assets/")&&!o.image_url.includes(".."))img.style.backgroundImage=`url(${JSON.stringify(o.image_url)})`;
  if(art[o.sku]&&!img.style.backgroundImage)img.style.backgroundImage=`url("/static/assets/${art[o.sku]}.png")`;
  const copy=node("div",null,"order-copy");copy.append(node("h2",o.product_name),node("p",o.merchant_name),node("p",`Quantity ${o.quantity} · ${o.currency}`),node("p",`BOUND order: ${o.order_id}`,"order-id"),node("p",timestamp(o.created_at)));
  const summary=node("div",null,"order-summary");summary.append(node("strong",amount(o.total,o.currency)),node("span",o.status_label,"badge"));
  if(o.status==="created")summary.append(node("span","Awaiting payment"));
  if(o.test_mode)summary.append(node("span","Razorpay Test Mode","badge amber"));
  const button=node("button","View details","secondary");button.onclick=()=>showDetails(o);summary.append(button);row.append(img,copy,summary);return row;
}
async function loadOrders(){
  const message=document.querySelector("#orders-message"),button=document.querySelector("#refresh-orders");button.disabled=true;
  try{const response=await fetch("/buyer/order-history",{headers:{Accept:"application/json"}});if(!response.ok)throw new Error();const data=await response.json();document.querySelector("#orders-list").replaceChildren(...data.orders.map(orderRow));message.textContent=data.orders.length?`${data.orders.length} order${data.orders.length===1?"":"s"} in this session`:"No orders yet. Native orders you create in the shopping workspace will appear here.";document.querySelector("#blocked-section").hidden=!data.blocked_attempts.length;document.querySelector("#blocked-list").replaceChildren(...data.blocked_attempts.map(e=>node("p",`${e.status_label} · ${timestamp(e.timestamp)} — ${e.message}`,"blocked-attempt")))}catch{message.textContent="Orders could not be loaded. Please try Refresh."}finally{button.disabled=false}
}
try{const buyer=JSON.parse(sessionStorage.getItem("boundBuyer")||"null");if(buyer?.name){document.querySelector("#buyer-name").textContent=buyer.name;document.querySelector("#buyer-initials").textContent=buyer.name.split(/\s+/).map(x=>x[0]).join("").slice(0,2).toUpperCase()}}catch{}
document.querySelector("#refresh-orders").onclick=loadOrders;
loadOrders();
