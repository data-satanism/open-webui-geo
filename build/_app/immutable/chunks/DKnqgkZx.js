import"./CWj6FrbW.js";import"./69_IOA4Y.js";import{p as Ke,g as Le,n as ve,q as I,u as Je,k as Qe,h as f,i as l,v as c,c as s,r as i,t as $,w as n,a as T,d as p,x as he,b as Ve,e as ge,s as Xe,m as C,y as K,l as E,f as q}from"./D2MbBfXk.js";import{i as ye}from"./DqGy336Y.js";import{r as L,s as k}from"./DlYHG1Qu.js";import{b as J}from"./D-olwNP2.js";import{p as y,b as xe}from"./BNmzLxS-.js";import{p as Ze}from"./Bfc47y5P.js";import{i as et}from"./DJROV0o1.js";import{t as we}from"./DuAdqNrc.js";import{g as tt}from"./CUe75Hth.js";import{u as at}from"./C078Vk_O.js";import{u as rt}from"./DLiQ2tPC.js";import{n as Q,e as st,f as it}from"./CY037-Sd.js";import{C as ot}from"./gmepGGfH.js";import{C as nt}from"./Di0Mh8FW.js";import{C as lt}from"./Cwb8Grv6.js";import{T as V}from"./DdFfZxnY.js";import{A as dt,a as ct}from"./DX7LFQFZ.js";import{S as ut}from"./CD5Xs9xV.js";var mt=q('<input class="w-full bg-transparent text-sm outline-hidden" type="text" required=""/>'),ft=q('<div class="shrink-0 truncate font-mono"> </div>'),pt=q('<input class="w-full bg-transparent font-mono outline-hidden disabled:text-gray-500" type="text" required=""/>'),_t=q('<input class="w-full bg-transparent outline-hidden" type="text" required=""/>'),vt=q('<div class="text-sm text-gray-500"><div class=" bg-yellow-500/20 text-yellow-700 dark:text-yellow-200 rounded-lg px-4 py-3"><div> </div> <ul class=" mt-1 list-disc pl-4 text-xs"><li> </li> <li> </li></ul></div> <div class="my-3"> </div></div>'),ht=q('<!> <div class="flex h-full w-full min-w-0 flex-col overflow-hidden"><form class="flex h-full min-h-0 min-w-0 flex-col"><button class="mb-1 flex h-6 w-fit items-center gap-1 rounded-md text-xs text-gray-400 transition-colors duration-75 hover:text-gray-700 dark:text-gray-600 dark:hover:text-gray-300" type="button"><!> <span> </span></button> <div class="flex shrink-0 items-start gap-2 pb-2 px-1"><div class="min-w-0 flex-1"><!> <div class="mt-0.5 flex min-w-0 items-center gap-2 text-xs text-gray-500"><!> <!></div></div> <div class="flex shrink-0 items-center gap-1 pr-0.5"><!></div></div> <div class="min-h-0 flex-1 overflow-hidden rounded-lg"><!></div> <div class="shrink-0 py-2 text-xs text-gray-500"><div class="flex items-center justify-between gap-3"><div class="min-w-0"><span class="font-normal dark:text-gray-200"> </span> <span class="font-normal dark:text-gray-400"> </span></div> <button class="flex h-7 shrink-0 items-center gap-1.5 rounded-lg bg-gray-900 px-2.5 text-xs text-white transition hover:bg-black disabled:opacity-60 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white" type="submit"> <!></button></div></div></form></div> <!>',1);function Ht(be,_){Ke(_,!1);const v=()=>ge(at,"$user",X),e=()=>ge($e,"$i18n",X),[X,ke]=Xe(),$e=Le("i18n");let P=C(null),A=C(!1),F=C(!1),H=C(!1),h=y(_,"edit",8,!1),Z=y(_,"clone",8,!1),Te=y(_,"onSave",8,async a=>{}),g=y(_,"id",12,""),x=y(_,"name",12,""),w=y(_,"meta",28,()=>({description:""})),b=y(_,"content",12,""),N=y(_,"accessGrants",28,()=>[]),S=C("");const Ce=()=>{f(S,b())};let D=C(),Ee=`import os
import requests
from datetime import datetime
from pydantic import BaseModel, Field

class Tools:
    def __init__(self):
        pass

    # Add your custom tools using pure Python code here, make sure to add type hints and descriptions
	
    def get_user_name_and_email_and_id(self, __user__: dict = {}) -> str:
        """
        Get the user name, Email and ID from the user object.
        """

        # Do not include a descrption for __user__ as it should not be shown in the tool's specification
        # The session user object will be passed as a parameter when the function is called

        print(__user__)
        result = ""

        if "name" in __user__:
            result += f"User: {__user__['name']}"
        if "id" in __user__:
            result += f" (ID: {__user__['id']})"
        if "email" in __user__:
            result += f" (Email: {__user__['email']})"

        if result == "":
            result = "User: Unknown"

        return result

    def get_current_time(self) -> str:
        """
        Get the current time in a more human-readable format.
        """

        now = datetime.now()
        current_time = now.strftime("%I:%M:%S %p")  # Using 12-hour format with AM/PM
        current_date = now.strftime(
            "%A, %B %d, %Y"
        )  # Full weekday, month name, day, and year

        return f"Current Date and Time = {current_date}, {current_time}"

    def calculator(
        self,
        equation: str = Field(
            ..., description="The mathematical equation to calculate."
        ),
    ) -> str:
        """
        Calculate the result of an equation.
        """

        # Avoid using eval in production code
        # https://nedbatchelder.com/blog/201206/eval_really_is_dangerous.html
        try:
            result = eval(equation)
            return f"{equation} = {result}"
        except Exception as e:
            print(e)
            return "Invalid equation"

    def get_current_weather(
        self,
        city: str = Field(
            "New York, NY", description="Get the current weather for a given city."
        ),
    ) -> str:
        """
        Get the current weather for a given city.
        """

        api_key = os.getenv("OPENWEATHER_API_KEY")
        if not api_key:
            return (
                "API key is not set in the environment variable 'OPENWEATHER_API_KEY'."
            )

        base_url = "http://api.openweathermap.org/data/2.5/weather"
        params = {
            "q": city,
            "appid": api_key,
            "units": "metric",  # Optional: Use 'imperial' for Fahrenheit
        }

        try:
            response = requests.get(base_url, params=params)
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx and 5xx)
            data = response.json()

            if data.get("cod") != 200:
                return f"Error fetching weather data: {data.get('message')}"

            weather_description = data["weather"][0]["description"]
            temperature = data["main"]["temp"]
            humidity = data["main"]["humidity"]
            wind_speed = data["wind"]["speed"]

            return f"Weather in {city}: {temperature}°C"
        except requests.RequestException as e:
            return f"Error fetching weather data: {str(e)}"
`;const qe=async()=>{f(A,!0);try{await Te()({id:g(),name:x(),meta:w(),content:b(),access_grants:N()})}finally{f(A,!1)}},ee=async()=>{if(l(D)){b(l(S)),await K();const a=await l(D).formatPythonCodeHandler();await K(),b(l(S)),await K(),a||console.warn("Code formatting failed or was skipped, saving unformatted code"),qe()}};ve(()=>I(b()),()=>{b()&&Ce()}),ve(()=>(I(x()),I(h()),I(Z()),Q),()=>{x()&&!h()&&!Z()&&g(Q(x()))}),Je(),et();var te=ht(),ae=Qe(te);{let a=E(()=>(v(),n(()=>{var t,r,d,m;return((d=(r=(t=v())==null?void 0:t.permissions)==null?void 0:r.sharing)==null?void 0:d.tools)||((m=v())==null?void 0:m.role)==="admin"}))),o=E(()=>(v(),n(()=>{var t,r,d,m;return((d=(r=(t=v())==null?void 0:t.permissions)==null?void 0:r.sharing)==null?void 0:d.public_tools)||((m=v())==null?void 0:m.role)==="admin"}))),u=E(()=>(v(),n(()=>{var t,r,d,m;return(((d=(r=(t=v())==null?void 0:t.permissions)==null?void 0:r.access_grants)==null?void 0:d.allow_users)??!0)||((m=v())==null?void 0:m.role)==="admin"})));dt(ae,{accessRoles:["read","write"],get share(){return l(a)},get sharePublic(){return l(o)},get shareUsers(){return l(u)},onChange:async()=>{if(h()&&g())try{await rt(localStorage.token,g(),N()),we.success(e().t("Saved"))}catch(t){we.error(`${t}`)}},get show(){return l(H)},set show(t){f(H,t)},get accessGrants(){return N()},set accessGrants(t){N(t)},$$legacy:!0})}var U=c(ae,2),G=s(U),M=s(G),re=s(M);lt(re,{className:"size-3",strokeWidth:"2"});var se=c(re,2),Ie=s(se,!0);i(se),i(M);var R=c(M,2),W=s(R),ie=s(W);{let a=E(()=>(e(),n(()=>e().t("e.g. My Tools"))));V(ie,{get content(){return l(a)},placement:"top-start",children:(o,u)=>{var t=mt();L(t),$((r,d)=>{k(t,"placeholder",r),k(t,"aria-label",d)},[()=>(e(),n(()=>e().t("Tool Name"))),()=>(e(),n(()=>e().t("Tool Name")))]),J(t,x),T(o,t)},$$slots:{default:!0}})}var oe=c(ie,2),ne=s(oe);{var Pe=a=>{var o=ft(),u=s(o,!0);i(o),$(()=>{k(o,"title",g()),p(u,g())}),T(a,o)},Ae=a=>{{let o=E(()=>(e(),n(()=>e().t("e.g. my_tools"))));V(a,{className:"min-w-[8rem] flex-1",get content(){return l(o)},placement:"top-start",children:(u,t)=>{var r=pt();L(r),$((d,m)=>{k(r,"placeholder",d),k(r,"aria-label",m),r.disabled=h()},[()=>(e(),n(()=>e().t("Tool ID"))),()=>(e(),n(()=>e().t("Tool ID")))]),J(r,g),T(u,r)},$$slots:{default:!0}})}};ye(ne,a=>{h()?a(Pe):a(Ae,-1)})}var Ne=c(ne,2);{let a=E(()=>(e(),n(()=>e().t("e.g. Tools for performing various operations"))));V(Ne,{className:"flex min-w-0 flex-1 items-center",get content(){return l(a)},placement:"top-start",children:(o,u)=>{var t=_t();L(t),$((r,d)=>{k(t,"placeholder",r),k(t,"aria-label",d)},[()=>(e(),n(()=>e().t("Tool Description"))),()=>(e(),n(()=>e().t("Tool Description")))]),J(t,()=>w().description,r=>w(w().description=r,!0)),T(o,t)},$$slots:{default:!0}})}i(oe),i(W);var le=c(W,2),Se=s(le);ct(Se,{$$events:{click:()=>{f(H,!0)}}}),i(le),i(R);var Y=c(R,2),De=s(Y);xe(ot(De,{get value(){return b()},lang:"python",boilerplate:Ee,className:"text-[0.6875rem]",onChange:a=>{if(f(S,a),!h()){const o=st(a);o.title&&!x()&&(x(it(o.title)),g(Q(o.title))),o.description&&!w().description&&w({...w(),description:o.description})}},onSave:async()=>{l(P)&&l(P).requestSubmit()},$$legacy:!0}),a=>f(D,a),()=>l(D)),i(Y);var de=c(Y,2),ce=s(de),j=s(ce),B=s(j),Ge=s(B,!0);i(B);var ue=c(B),me=c(ue),Me=s(me,!0);i(me),i(j);var O=c(j,2),fe=s(O),Fe=c(fe);{var He=a=>{ut(a,{className:"size-3"})};ye(Fe,a=>{l(A)&&a(He)})}i(O),i(ce),i(de),i(G),xe(G,a=>f(P,a),()=>l(P)),i(U);var Ue=c(U,2);nt(Ue,{get show(){return l(F)},set show(a){f(F,a)},$$events:{confirm:()=>{ee()}},children:(a,o)=>{var u=vt(),t=s(u),r=s(t),d=s(r,!0);i(r);var m=c(r,2),z=s(m),Re=s(z,!0);i(z);var pe=c(z,2),We=s(pe,!0);i(pe),i(m),i(t);var _e=c(t,2),Ye=s(_e,!0);i(_e),i(u),$((je,Be,Oe,ze)=>{p(d,je),p(Re,Be),p(We,Oe),p(Ye,ze)},[()=>(e(),n(()=>e().t("Please carefully review the following warnings:"))),()=>(e(),n(()=>e().t("Tools have a function calling system that allows arbitrary code execution."))),()=>(e(),n(()=>e().t("Do not install tools from sources you do not fully trust."))),()=>(e(),n(()=>e().t("I acknowledge that I have read and I understand the implications of my action. I am aware of the risks associated with executing arbitrary code and I have verified the trustworthiness of the source.")))]),T(a,u)},$$slots:{default:!0},$$legacy:!0}),$((a,o,u,t,r)=>{p(Ie,a),p(Ge,o),p(ue,` ${u??""} `),p(Me,t),O.disabled=l(A),p(fe,`${r??""} `)},[()=>(e(),n(()=>e().t("Back"))),()=>(e(),n(()=>e().t("Warning:"))),()=>(e(),n(()=>e().t("Tools can execute arbitrary code."))),()=>(e(),n(()=>e().t("Only install tools from sources you trust."))),()=>(e(),I(h()),n(()=>e().t(h()?"Save":"Save & Create")))]),he("click",M,()=>{tt("/workspace/tools")}),he("submit",G,Ze(()=>{h()?ee():f(F,!0)})),T(be,te),Ve(),ke()}export{Ht as T};
//# sourceMappingURL=DKnqgkZx.js.map
