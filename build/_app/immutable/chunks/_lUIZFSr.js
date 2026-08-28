import"./CWj6FrbW.js";import"./69_IOA4Y.js";import{p as Je,g as Ke,n as he,q as P,u as Qe,k as Re,c as r,v as c,r as i,t as b,w as n,a as w,i as l,h as u,d as f,x as G,b as Xe,e as Ye,s as Ze,m as k,y as J,l as K,f as I}from"./D2MbBfXk.js";import{i as Q}from"./DqGy336Y.js";import{r as R,s as g,b as et}from"./DlYHG1Qu.js";import{b as X}from"./D-olwNP2.js";import{p as F,b as ge}from"./BNmzLxS-.js";import{p as tt}from"./Bfc47y5P.js";import{i as at}from"./DJROV0o1.js";import{g as rt}from"./CUe75Hth.js";import{n as Y,e as it,f as st}from"./CY037-Sd.js";import{C as nt}from"./gmepGGfH.js";import{C as ot}from"./Di0Mh8FW.js";import{S as lt}from"./CD5Xs9xV.js";import{T as Z}from"./DdFfZxnY.js";import{C as dt}from"./Cwb8Grv6.js";var ct=I('<input class="w-full bg-transparent text-sm outline-hidden" type="text" required=""/>'),ut=I('<div class="shrink-0 truncate font-mono"> </div>'),ft=I('<input class="w-full bg-transparent font-mono outline-hidden disabled:text-gray-500" type="text" required=""/>'),vt=I('<input class="w-full bg-transparent outline-hidden" type="text" required=""/>'),pt=I('<select class="h-7 rounded-lg border border-gray-100 bg-transparent px-2 text-xs outline-hidden dark:border-gray-800"><option> </option><option> </option></select>'),_t=I('<div class="text-sm text-gray-500"><div class=" bg-yellow-500/20 text-yellow-700 dark:text-yellow-200 rounded-lg px-4 py-3"><div> </div> <ul class=" mt-1 list-disc pl-4 text-xs"><li> </li> <li> </li></ul></div> <div class="my-3"> </div></div>'),mt=I('<div class="flex h-full w-full min-w-0 flex-col overflow-hidden"><form class="flex h-full min-h-0 min-w-0 flex-col"><button class="mb-1 flex h-6 w-fit items-center gap-1 rounded-md text-xs text-gray-400 transition-colors duration-75 hover:text-gray-700 dark:text-gray-600 dark:hover:text-gray-300" type="button"><!> <span> </span></button> <div class="flex shrink-0 items-start gap-2 pb-2 px-1"><div class="min-w-0 flex-1"><!> <div class="mt-0.5 flex min-w-0 items-center gap-2 text-xs text-gray-500"><!> <!></div></div> <div class="flex shrink-0 items-center gap-1"><!></div></div> <div class="min-h-0 flex-1 overflow-hidden rounded-lg"><!></div> <div class="shrink-0 py-2 text-xs text-gray-500"><div class="flex items-center justify-between gap-3"><div class="min-w-0"><span class="font-normal dark:text-gray-200"> </span> <span class="font-normal dark:text-gray-400"> </span></div> <button class="flex h-7 shrink-0 items-center gap-1.5 rounded-lg bg-gray-900 px-2.5 text-xs text-white transition hover:bg-black disabled:opacity-60 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white" type="submit"> <!></button></div></div></form></div> <!>',1);function Et(xe,m){Je(m,!1);const e=()=>Ye(we,"$i18n",ye),[ye,be]=Ze(),we=Ke("i18n");let M=k(null),S=k(!1),A=k(!1),ke=F(m,"onSave",8,async t=>{}),p=F(m,"edit",8,!1),ee=F(m,"clone",8,!1),$=F(m,"id",12,""),x=F(m,"name",12,""),y=F(m,"meta",28,()=>({description:""})),h=F(m,"content",12,""),N=k("");const Fe=()=>{u(N,h())};let T=k(),D=k("filter");const te=`"""
title: Example Filter
author: open-webui
author_url: https://github.com/open-webui
funding_url: https://github.com/open-webui
version: 0.1
"""

from pydantic import BaseModel, Field
from typing import Optional


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=0, description="Priority level for the filter operations."
        )
        max_turns: int = Field(
            default=8, description="Maximum allowable conversation turns for a user."
        )
        pass

    class UserValves(BaseModel):
        max_turns: int = Field(
            default=4, description="Maximum allowable conversation turns for a user."
        )
        pass

    def __init__(self):
        # Indicates custom file handling logic. This flag helps disengage default routines in favor of custom
        # implementations, informing the WebUI to defer file-related operations to designated methods within this class.
        # Alternatively, you can remove the files directly from the body in from the inlet hook
        # self.file_handler = True

        # Initialize 'valves' with specific configurations. Using 'Valves' instance helps encapsulate settings,
        # which ensures settings are managed cohesively and not confused with operational flags like 'file_handler'.
        self.valves = self.Valves()
        pass

    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        # Modify the request body or validate it before processing by the chat completion API.
        # This function is the pre-processor for the API where various checks on the input can be performed.
        # It can also modify the request before sending it to the API.
        print(f"inlet:{__name__}")
        print(f"inlet:body:{body}")
        print(f"inlet:user:{__user__}")

        if __user__.get("role", "admin") in ["user", "admin"]:
            messages = body.get("messages", [])

            max_turns = min(__user__["valves"].max_turns, self.valves.max_turns)
            if len(messages) > max_turns:
                raise Exception(
                    f"Conversation turn limit exceeded. Max turns: {max_turns}"
                )

        return body

    def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        # Modify or analyze the response body after processing by the API.
        # This function is the post-processor for the API, which can be used to modify the response
        # or perform additional checks and analytics.
        print(f"outlet:{__name__}")
        print(f"outlet:body:{body}")
        print(f"outlet:user:{__user__}")

        return body
`,Ie=`"""
title: Example Event
author: open-webui
author_url: https://github.com/open-webui
funding_url: https://github.com/open-webui
version: 0.1
"""

from pydantic import BaseModel


class Event:
    class Valves(BaseModel):
        pass

    def __init__(self):
        self.valves = self.Valves()

    async def event(
        self,
        event: dict,
        __event_id__: str = None,
        __event_name__: str = None,
        __id__: str = None,
        __app__=None,
        __request__=None,
    ):
        print(f"event:{__name__}")
        print(f"event:id:{__event_id__}")
        print(f"event:name:{__event_name__}")
        print(f"event:payload:{event}")
`;let E=k(te);const $e=t=>{u(D,t),u(E,t==="event"?Ie:te),h(l(E)),u(N,l(E))},Ne=t=>{$e(t==="event"?"event":"filter")},Ce=async()=>{u(S,!0);try{await ke()({id:$(),name:x(),meta:y(),content:h()})}finally{u(S,!1)}},ae=async()=>{if(l(T)){h(l(N)),await J();const t=await l(T).formatPythonCodeHandler();await J(),h(l(N)),await J(),t||console.warn("Code formatting failed or was skipped, saving unformatted code"),Ce()}};he(()=>P(h()),()=>{h()&&Fe()}),he(()=>(P(x()),P(p()),P(ee()),Y),()=>{x()&&!p()&&!ee()&&$(Y(x()))}),Qe(),at();var re=mt(),V=Re(re),q=r(V),B=r(q),ie=r(B);dt(ie,{className:"size-3",strokeWidth:"2"});var se=c(ie,2),Pe=r(se,!0);i(se),i(B);var z=c(B,2),O=r(z),ne=r(O);{let t=K(()=>(e(),n(()=>e().t("e.g. My Filter"))));Z(ne,{get content(){return l(t)},placement:"top-start",children:(a,d)=>{var o=ct();R(o),b((s,_)=>{g(o,"placeholder",s),g(o,"aria-label",_)},[()=>(e(),n(()=>e().t("Function Name"))),()=>(e(),n(()=>e().t("Function Name")))]),X(o,x),w(a,o)},$$slots:{default:!0}})}var oe=c(ne,2),le=r(oe);{var Me=t=>{var a=ut(),d=r(a,!0);i(a),b(()=>{g(a,"title",$()),f(d,$())}),w(t,a)},Se=t=>{{let a=K(()=>(e(),n(()=>e().t("e.g. my_filter"))));Z(t,{className:"min-w-[8rem] flex-1",get content(){return l(a)},placement:"top-start",children:(d,o)=>{var s=ft();R(s),b((_,v)=>{g(s,"placeholder",_),g(s,"aria-label",v),s.disabled=p()},[()=>(e(),n(()=>e().t("Function ID"))),()=>(e(),n(()=>e().t("Function ID")))]),X(s,$),w(d,s)},$$slots:{default:!0}})}};Q(le,t=>{p()?t(Me):t(Se,-1)})}var Te=c(le,2);{let t=K(()=>(e(),n(()=>e().t("e.g. A filter to remove profanity from text"))));Z(Te,{className:"flex min-w-0 flex-1 items-center",get content(){return l(t)},placement:"top-start",children:(a,d)=>{var o=vt();R(o),b((s,_)=>{g(o,"placeholder",s),g(o,"aria-label",_)},[()=>(e(),n(()=>e().t("Function Description"))),()=>(e(),n(()=>e().t("Function Description")))]),X(o,()=>y().description,s=>y(y().description=s,!0)),w(a,o)},$$slots:{default:!0}})}i(oe),i(O);var de=c(O,2),Ee=r(de);{var qe=t=>{var a=pt(),d=r(a),o=r(d,!0);i(d),d.value=d.__value="filter";var s=c(d),_=r(s,!0);i(s),s.value=s.__value="event",i(a),b((v,C,L)=>{g(a,"aria-label",v),f(o,C),f(_,L)},[()=>(e(),n(()=>e().t("Function starter"))),()=>(e(),n(()=>e().t("Filter"))),()=>(e(),n(()=>e().t("Event")))]),et(a,()=>l(D),v=>u(D,v)),G("change",a,v=>Ne(v.currentTarget.value)),w(t,a)};Q(Ee,t=>{p()||t(qe)})}i(de),i(z);var H=c(z,2),Be=r(H);ge(nt(Be,{get value(){return h()},lang:"python",get boilerplate(){return l(E)},className:"text-[0.6875rem]",onChange:t=>{if(u(N,t),!p()){const a=it(t);a.title&&!x()&&(x(st(a.title)),$(Y(a.title))),a.description&&!y().description&&y({...y(),description:a.description})}},onSave:async()=>{l(M)&&l(M).requestSubmit()},$$legacy:!0}),t=>u(T,t),()=>l(T)),i(H);var ce=c(H,2),ue=r(ce),U=r(ue),W=r(U),Ae=r(W,!0);i(W);var fe=c(W),ve=c(fe),De=r(ve,!0);i(ve),i(U);var j=c(U,2),pe=r(j),Ve=c(pe);{var ze=t=>{lt(t,{className:"size-3"})};Q(Ve,t=>{l(S)&&t(ze)})}i(j),i(ue),i(ce),i(q),ge(q,t=>u(M,t),()=>l(M)),i(V);var Oe=c(V,2);ot(Oe,{get show(){return l(A)},set show(t){u(A,t)},$$events:{confirm:()=>{ae()}},children:(t,a)=>{var d=_t(),o=r(d),s=r(o),_=r(s,!0);i(s);var v=c(s,2),C=r(v),L=r(C,!0);i(C);var _e=c(C,2),He=r(_e,!0);i(_e),i(v),i(o);var me=c(o,2),Ue=r(me,!0);i(me),i(d),b((We,je,Le,Ge)=>{f(_,We),f(L,je),f(He,Le),f(Ue,Ge)},[()=>(e(),n(()=>e().t("Please carefully review the following warnings:"))),()=>(e(),n(()=>e().t("Functions allow arbitrary code execution."))),()=>(e(),n(()=>e().t("Do not install functions from sources you do not fully trust."))),()=>(e(),n(()=>e().t("I acknowledge that I have read and I understand the implications of my action. I am aware of the risks associated with executing arbitrary code and I have verified the trustworthiness of the source.")))]),w(t,d)},$$slots:{default:!0},$$legacy:!0}),b((t,a,d,o,s)=>{f(Pe,t),f(Ae,a),f(fe,` ${d??""} `),f(De,o),j.disabled=l(S),f(pe,`${s??""} `)},[()=>(e(),n(()=>e().t("Back"))),()=>(e(),n(()=>e().t("Warning:"))),()=>(e(),n(()=>e().t("Functions can execute arbitrary code."))),()=>(e(),n(()=>e().t("Only install functions from sources you trust."))),()=>(e(),P(p()),n(()=>e().t(p()?"Save":"Save & Create")))]),G("click",B,()=>{rt("/admin/functions")}),G("submit",q,tt(()=>{p()?ae():u(A,!0)})),w(xe,re),Xe(),be()}export{Et as F};
//# sourceMappingURL=_lUIZFSr.js.map
