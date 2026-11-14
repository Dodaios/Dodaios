import{g as we,s as _e,p as De,o as Se,a as Ce,b as Me,_ as l,c as dt,d as Ee,aX as U,l as ot,j as Ie,n as $e,q as Ye,y as Ae}from"./index-CUvMS5Y6.js";import{cM as $t}from"./index-CgF0P-7W.js";import{s as vt}from"./d3-selection-D5hwjrp8.js";import{t as Fe,l as Le,a as Qt,c as Kt,d as Oe,e as We,g as Ne,h as Pe,i as Ve,j as ze,k as Re,m as Jt,n as te,p as ee,s as re,q as ne}from"./d3-scale-CXz7lZMf.js";import{h as He}from"./d3-interpolate-BSNsLNjT.js";import"./d3-path-CgeVrazB.js";import"./modulepreload-polyfill-B5Qt9EMX.js";function Tt(t,e){return t==null||e==null?NaN:t<e?-1:t>e?1:t>=e?0:NaN}function Be(t,e){return t==null||e==null?NaN:e<t?-1:e>t?1:e>=t?0:NaN}function fe(t){let e,n,r;t.length!==2?(e=Tt,n=(p,_)=>Tt(t(p),_),r=(p,_)=>t(p)-_):(e=t===Tt||t===Be?t:qe,n=t,r=t);function i(p,_,D=0,w=p.length){if(D<w){if(e(_,_)!==0)return w;do{const I=D+w>>>1;n(p[I],_)<0?D=I+1:w=I}while(D<w)}return D}function g(p,_,D=0,w=p.length){if(D<w){if(e(_,_)!==0)return w;do{const I=D+w>>>1;n(p[I],_)<=0?D=I+1:w=I}while(D<w)}return D}function k(p,_,D=0,w=p.length){const I=i(p,_,D,w-1);return I>D&&r(p[I-1],_)>-r(p[I],_)?I-1:I}return{left:i,center:k,right:g}}function qe(){return 0}function Ge(t){return t===null?NaN:+t}fe(Tt);fe(Ge).center;function Xe(t,e){let n;if(e===void 0)for(const r of t)r!=null&&(n<r||n===void 0&&r>=r)&&(n=r);else{let r=-1;for(let i of t)(i=e(i,++r,t))!=null&&(n<i||n===void 0&&i>=i)&&(n=i)}return n}function je(t,e){let n;if(e===void 0)for(const r of t)r!=null&&(n>r||n===void 0&&r>=r)&&(n=r);else{let r=-1;for(let i of t)(i=e(i,++r,t))!=null&&(n>i||n===void 0&&i>=i)&&(n=i)}return n}function Ue(t){return t}var bt=1,At=2,Lt=3,xt=4,ie=1e-6;function Ze(t){return"translate("+t+",0)"}function Qe(t){return"translate(0,"+t+")"}function Ke(t){return e=>+t(e)}function Je(t,e){return e=Math.max(0,t.bandwidth()-e*2)/2,t.round()&&(e=Math.round(e)),n=>+t(n)+e}function tr(){return!this.__axis}function he(t,e){var n=[],r=null,i=null,g=6,k=6,p=3,_=typeof window<"u"&&window.devicePixelRatio>1?0:.5,D=t===bt||t===xt?-1:1,w=t===xt||t===At?"x":"y",I=t===bt||t===Lt?Ze:Qe;function S(C){var G=r??(e.ticks?e.ticks.apply(e,n):e.domain()),R=i??(e.tickFormat?e.tickFormat.apply(e,n):Ue),y=Math.max(g,0)+p,E=e.range(),N=+E[0]+_,W=+E[E.length-1]+_,H=(e.bandwidth?Je:Ke)(e.copy(),_),z=C.selection?C.selection():C,Y=z.selectAll(".domain").data([null]),T=z.selectAll(".tick").data(G,e).order(),h=T.exit(),$=T.enter().append("g").attr("class","tick"),f=T.select("line"),b=T.select("text");Y=Y.merge(Y.enter().insert("path",".tick").attr("class","domain").attr("stroke","currentColor")),T=T.merge($),f=f.merge($.append("line").attr("stroke","currentColor").attr(w+"2",D*g)),b=b.merge($.append("text").attr("fill","currentColor").attr(w,D*y).attr("dy",t===bt?"0em":t===Lt?"0.71em":"0.32em")),C!==z&&(Y=Y.transition(C),T=T.transition(C),f=f.transition(C),b=b.transition(C),h=h.transition(C).attr("opacity",ie).attr("transform",function(x){return isFinite(x=H(x))?I(x+_):this.getAttribute("transform")}),$.attr("opacity",ie).attr("transform",function(x){var v=this.parentNode.__axis;return I((v&&isFinite(v=v(x))?v:H(x))+_)})),h.remove(),Y.attr("d",t===xt||t===At?k?"M"+D*k+","+N+"H"+_+"V"+W+"H"+D*k:"M"+_+","+N+"V"+W:k?"M"+N+","+D*k+"V"+_+"H"+W+"V"+D*k:"M"+N+","+_+"H"+W),T.attr("opacity",1).attr("transform",function(x){return I(H(x)+_)}),f.attr(w+"2",D*g),b.attr(w,D*y).text(R),z.filter(tr).attr("fill","none").attr("font-size",10).attr("font-family","sans-serif").attr("text-anchor",t===At?"start":t===xt?"end":"middle"),z.each(function(){this.__axis=H})}return S.scale=function(C){return arguments.length?(e=C,S):e},S.ticks=function(){return n=Array.from(arguments),S},S.tickArguments=function(C){return arguments.length?(n=C==null?[]:Array.from(C),S):n.slice()},S.tickValues=function(C){return arguments.length?(r=C==null?null:Array.from(C),S):r&&r.slice()},S.tickFormat=function(C){return arguments.length?(i=C,S):i},S.tickSize=function(C){return arguments.length?(g=k=+C,S):g},S.tickSizeInner=function(C){return arguments.length?(g=+C,S):g},S.tickSizeOuter=function(C){return arguments.length?(k=+C,S):k},S.tickPadding=function(C){return arguments.length?(p=+C,S):p},S.offset=function(C){return arguments.length?(_=+C,S):_},S}function er(t){return he(bt,t)}function rr(t){return he(Lt,t)}var wt={exports:{}},nr=wt.exports,se;function ir(){return se||(se=1,(function(t,e){(function(n,r){t.exports=r()})(nr,(function(){var n="day";return function(r,i,g){var k=function(D){return D.add(4-D.isoWeekday(),n)},p=i.prototype;p.isoWeekYear=function(){return k(this).year()},p.isoWeek=function(D){if(!this.$utils().u(D))return this.add(7*(D-this.isoWeek()),n);var w,I,S,C,G=k(this),R=(w=this.isoWeekYear(),I=this.$u,S=(I?g.utc:g)().year(w).startOf("year"),C=4-S.isoWeekday(),S.isoWeekday()>4&&(C+=7),S.add(C,n));return G.diff(R,"week")+1},p.isoWeekday=function(D){return this.$utils().u(D)?this.day()||7:this.day(this.day()%7?D:D-7)};var _=p.startOf;p.startOf=function(D,w){var I=this.$utils(),S=!!I.u(w)||w;return I.p(D)==="isoweek"?S?this.date(this.date()-(this.isoWeekday()-1)).startOf("day"):this.date(this.date()-1-(this.isoWeekday()-1)+7).endOf("day"):_.bind(this)(D,w)}}}))})(wt)),wt.exports}var sr=ir();const ar=$t(sr);var _t={exports:{}},or=_t.exports,ae;function cr(){return ae||(ae=1,(function(t,e){(function(n,r){t.exports=r()})(or,(function(){var n={LTS:"h:mm:ss A",LT:"h:mm A",L:"MM/DD/YYYY",LL:"MMMM D, YYYY",LLL:"MMMM D, YYYY h:mm A",LLLL:"dddd, MMMM D, YYYY h:mm A"},r=/(\[[^[]*\])|([-_:/.,()\s]+)|(A|a|Q|YYYY|YY?|ww?|MM?M?M?|Do|DD?|hh?|HH?|mm?|ss?|S{1,3}|z|ZZ?)/g,i=/\d/,g=/\d\d/,k=/\d\d?/,p=/\d*[^-_:/,()\s\d]+/,_={},D=function(y){return(y=+y)+(y>68?1900:2e3)},w=function(y){return function(E){this[y]=+E}},I=[/[+-]\d\d:?(\d\d)?|Z/,function(y){(this.zone||(this.zone={})).offset=(function(E){if(!E||E==="Z")return 0;var N=E.match(/([+-]|\d\d)/g),W=60*N[1]+(+N[2]||0);return W===0?0:N[0]==="+"?-W:W})(y)}],S=function(y){var E=_[y];return E&&(E.indexOf?E:E.s.concat(E.f))},C=function(y,E){var N,W=_.meridiem;if(W){for(var H=1;H<=24;H+=1)if(y.indexOf(W(H,0,E))>-1){N=H>12;break}}else N=y===(E?"pm":"PM");return N},G={A:[p,function(y){this.afternoon=C(y,!1)}],a:[p,function(y){this.afternoon=C(y,!0)}],Q:[i,function(y){this.month=3*(y-1)+1}],S:[i,function(y){this.milliseconds=100*+y}],SS:[g,function(y){this.milliseconds=10*+y}],SSS:[/\d{3}/,function(y){this.milliseconds=+y}],s:[k,w("seconds")],ss:[k,w("seconds")],m:[k,w("minutes")],mm:[k,w("minutes")],H:[k,w("hours")],h:[k,w("hours")],HH:[k,w("hours")],hh:[k,w("hours")],D:[k,w("day")],DD:[g,w("day")],Do:[p,function(y){var E=_.ordinal,N=y.match(/\d+/);if(this.day=N[0],E)for(var W=1;W<=31;W+=1)E(W).replace(/\[|\]/g,"")===y&&(this.day=W)}],w:[k,w("week")],ww:[g,w("week")],M:[k,w("month")],MM:[g,w("month")],MMM:[p,function(y){var E=S("months"),N=(S("monthsShort")||E.map((function(W){return W.slice(0,3)}))).indexOf(y)+1;if(N<1)throw new Error;this.month=N%12||N}],MMMM:[p,function(y){var E=S("months").indexOf(y)+1;if(E<1)throw new Error;this.month=E%12||E}],Y:[/[+-]?\d+/,w("year")],YY:[g,function(y){this.year=D(y)}],YYYY:[/\d{4}/,w("year")],Z:I,ZZ:I};function R(y){var E,N;E=y,N=_&&_.formats;for(var W=(y=E.replace(/(\[[^\]]+])|(LTS?|l{1,4}|L{1,4})/g,(function(f,b,x){var v=x&&x.toUpperCase();return b||N[x]||n[x]||N[v].replace(/(\[[^\]]+])|(MMMM|MM|DD|dddd)/g,(function(a,d,m){return d||m.slice(1)}))}))).match(r),H=W.length,z=0;z<H;z+=1){var Y=W[z],T=G[Y],h=T&&T[0],$=T&&T[1];W[z]=$?{regex:h,parser:$}:Y.replace(/^\[|\]$/g,"")}return function(f){for(var b={},x=0,v=0;x<H;x+=1){var a=W[x];if(typeof a=="string")v+=a.length;else{var d=a.regex,m=a.parser,u=f.slice(v),M=d.exec(u)[0];m.call(b,M),f=f.replace(M,"")}}return(function(s){var A=s.afternoon;if(A!==void 0){var o=s.hours;A?o<12&&(s.hours+=12):o===12&&(s.hours=0),delete s.afternoon}})(b),b}}return function(y,E,N){N.p.customParseFormat=!0,y&&y.parseTwoDigitYear&&(D=y.parseTwoDigitYear);var W=E.prototype,H=W.parse;W.parse=function(z){var Y=z.date,T=z.utc,h=z.args;this.$u=T;var $=h[1];if(typeof $=="string"){var f=h[2]===!0,b=h[3]===!0,x=f||b,v=h[2];b&&(v=h[2]),_=this.$locale(),!f&&v&&(_=N.Ls[v]),this.$d=(function(u,M,s,A){try{if(["x","X"].indexOf(M)>-1)return new Date((M==="X"?1e3:1)*u);var o=R(M)(u),q=o.year,c=o.month,F=o.day,L=o.hours,V=o.minutes,O=o.seconds,B=o.milliseconds,P=o.zone,nt=o.week,st=new Date,yt=F||(q||c?1:st.getDate()),lt=q||st.getFullYear(),X=0;q&&!c||(X=c>0?c-1:st.getMonth());var K,Z=L||0,at=V||0,J=O||0,it=B||0;return P?new Date(Date.UTC(lt,X,yt,Z,at,J,it+60*P.offset*1e3)):s?new Date(Date.UTC(lt,X,yt,Z,at,J,it)):(K=new Date(lt,X,yt,Z,at,J,it),nt&&(K=A(K).week(nt).toDate()),K)}catch{return new Date("")}})(Y,$,T,N),this.init(),v&&v!==!0&&(this.$L=this.locale(v).$L),x&&Y!=this.format($)&&(this.$d=new Date("")),_={}}else if($ instanceof Array)for(var a=$.length,d=1;d<=a;d+=1){h[1]=$[d-1];var m=N.apply(this,h);if(m.isValid()){this.$d=m.$d,this.$L=m.$L,this.init();break}d===a&&(this.$d=new Date(""))}else H.call(this,z)}}}))})(_t)),_t.exports}var lr=cr();const ur=$t(lr);var Dt={exports:{}},dr=Dt.exports,oe;function fr(){return oe||(oe=1,(function(t,e){(function(n,r){t.exports=r()})(dr,(function(){return function(n,r){var i=r.prototype,g=i.format;i.format=function(k){var p=this,_=this.$locale();if(!this.isValid())return g.bind(this)(k);var D=this.$utils(),w=(k||"YYYY-MM-DDTHH:mm:ssZ").replace(/\[([^\]]+)]|Q|wo|ww|w|WW|W|zzz|z|gggg|GGGG|Do|X|x|k{1,2}|S/g,(function(I){switch(I){case"Q":return Math.ceil((p.$M+1)/3);case"Do":return _.ordinal(p.$D);case"gggg":return p.weekYear();case"GGGG":return p.isoWeekYear();case"wo":return _.ordinal(p.week(),"W");case"w":case"ww":return D.s(p.week(),I==="w"?1:2,"0");case"W":case"WW":return D.s(p.isoWeek(),I==="W"?1:2,"0");case"k":case"kk":return D.s(String(p.$H===0?24:p.$H),I==="k"?1:2,"0");case"X":return Math.floor(p.$d.getTime()/1e3);case"x":return p.$d.getTime();case"z":return"["+p.offsetName()+"]";case"zzz":return"["+p.offsetName("long")+"]";default:return I}}));return g.bind(this)(w)}}}))})(Dt)),Dt.exports}var hr=fr();const mr=$t(hr);var St={exports:{}},kr=St.exports,ce;function yr(){return ce||(ce=1,(function(t,e){(function(n,r){t.exports=r()})(kr,(function(){var n,r,i=1e3,g=6e4,k=36e5,p=864e5,_=31536e6,D=2628e6,w=/^(-|\+)?P(?:([-+]?[0-9,.]*)Y)?(?:([-+]?[0-9,.]*)M)?(?:([-+]?[0-9,.]*)W)?(?:([-+]?[0-9,.]*)D)?(?:T(?:([-+]?[0-9,.]*)H)?(?:([-+]?[0-9,.]*)M)?(?:([-+]?[0-9,.]*)S)?)?$/,I=/\[([^\]]+)]|YYYY|YY|Y|M{1,2}|D{1,2}|H{1,2}|m{1,2}|s{1,2}|SSS/g,S={years:_,months:D,days:p,hours:k,minutes:g,seconds:i,milliseconds:1,weeks:6048e5},C=function(Y){return Y instanceof H},G=function(Y,T,h){return new H(Y,h,T.$l)},R=function(Y){return r.p(Y)+"s"},y=function(Y){return Y<0},E=function(Y){return y(Y)?Math.ceil(Y):Math.floor(Y)},N=function(Y){return Math.abs(Y)},W=function(Y,T){return Y?y(Y)?{negative:!0,format:""+N(Y)+T}:{negative:!1,format:""+Y+T}:{negative:!1,format:""}},H=(function(){function Y(h,$,f){var b=this;if(this.$d={},this.$l=f,h===void 0&&(this.$ms=0,this.parseFromMilliseconds()),$)return G(h*S[R($)],this);if(typeof h=="number")return this.$ms=h,this.parseFromMilliseconds(),this;if(typeof h=="object")return Object.keys(h).forEach((function(a){b.$d[R(a)]=h[a]})),this.calMilliseconds(),this;if(typeof h=="string"){var x=h.match(w);if(x){var v=x.slice(2).map((function(a){return a!=null?Number(a):0}));return this.$d.years=v[0],this.$d.months=v[1],this.$d.weeks=v[2],this.$d.days=v[3],this.$d.hours=v[4],this.$d.minutes=v[5],this.$d.seconds=v[6],this.calMilliseconds(),this}}return this}var T=Y.prototype;return T.calMilliseconds=function(){var h=this;this.$ms=Object.keys(this.$d).reduce((function($,f){return $+(h.$d[f]||0)*S[f]}),0)},T.parseFromMilliseconds=function(){var h=this.$ms;this.$d.years=E(h/_),h%=_,this.$d.months=E(h/D),h%=D,this.$d.days=E(h/p),h%=p,this.$d.hours=E(h/k),h%=k,this.$d.minutes=E(h/g),h%=g,this.$d.seconds=E(h/i),h%=i,this.$d.milliseconds=h},T.toISOString=function(){var h=W(this.$d.years,"Y"),$=W(this.$d.months,"M"),f=+this.$d.days||0;this.$d.weeks&&(f+=7*this.$d.weeks);var b=W(f,"D"),x=W(this.$d.hours,"H"),v=W(this.$d.minutes,"M"),a=this.$d.seconds||0;this.$d.milliseconds&&(a+=this.$d.milliseconds/1e3,a=Math.round(1e3*a)/1e3);var d=W(a,"S"),m=h.negative||$.negative||b.negative||x.negative||v.negative||d.negative,u=x.format||v.format||d.format?"T":"",M=(m?"-":"")+"P"+h.format+$.format+b.format+u+x.format+v.format+d.format;return M==="P"||M==="-P"?"P0D":M},T.toJSON=function(){return this.toISOString()},T.format=function(h){var $=h||"YYYY-MM-DDTHH:mm:ss",f={Y:this.$d.years,YY:r.s(this.$d.years,2,"0"),YYYY:r.s(this.$d.years,4,"0"),M:this.$d.months,MM:r.s(this.$d.months,2,"0"),D:this.$d.days,DD:r.s(this.$d.days,2,"0"),H:this.$d.hours,HH:r.s(this.$d.hours,2,"0"),m:this.$d.minutes,mm:r.s(this.$d.minutes,2,"0"),s:this.$d.seconds,ss:r.s(this.$d.seconds,2,"0"),SSS:r.s(this.$d.milliseconds,3,"0")};return $.replace(I,(function(b,x){return x||String(f[b])}))},T.as=function(h){return this.$ms/S[R(h)]},T.get=function(h){var $=this.$ms,f=R(h);return f==="milliseconds"?$%=1e3:$=f==="weeks"?E($/S[f]):this.$d[f],$||0},T.add=function(h,$,f){var b;return b=$?h*S[R($)]:C(h)?h.$ms:G(h,this).$ms,G(this.$ms+b*(f?-1:1),this)},T.subtract=function(h,$){return this.add(h,$,!0)},T.locale=function(h){var $=this.clone();return $.$l=h,$},T.clone=function(){return G(this.$ms,this)},T.humanize=function(h){return n().add(this.$ms,"ms").locale(this.$l).fromNow(!h)},T.valueOf=function(){return this.asMilliseconds()},T.milliseconds=function(){return this.get("milliseconds")},T.asMilliseconds=function(){return this.as("milliseconds")},T.seconds=function(){return this.get("seconds")},T.asSeconds=function(){return this.as("seconds")},T.minutes=function(){return this.get("minutes")},T.asMinutes=function(){return this.as("minutes")},T.hours=function(){return this.get("hours")},T.asHours=function(){return this.as("hours")},T.days=function(){return this.get("days")},T.asDays=function(){return this.as("days")},T.weeks=function(){return this.get("weeks")},T.asWeeks=function(){return this.as("weeks")},T.months=function(){return this.get("months")},T.asMonths=function(){return this.as("months")},T.years=function(){return this.get("years")},T.asYears=function(){return this.as("years")},Y})(),z=function(Y,T,h){return Y.add(T.years()*h,"y").add(T.months()*h,"M").add(T.days()*h,"d").add(T.hours()*h,"h").add(T.minutes()*h,"m").add(T.seconds()*h,"s").add(T.milliseconds()*h,"ms")};return function(Y,T,h){n=h,r=h().$utils(),h.duration=function(b,x){var v=h.locale();return G(b,{$l:v},x)},h.isDuration=C;var $=T.prototype.add,f=T.prototype.subtract;T.prototype.add=function(b,x){return C(b)?z(this,b,1):$.bind(this)(b,x)},T.prototype.subtract=function(b,x){return C(b)?z(this,b,-1):f.bind(this)(b,x)}}}))})(St)),St.exports}var gr=yr();const pr=$t(gr);var Ot=(function(){var t=l(function(v,a,d,m){for(d=d||{},m=v.length;m--;d[v[m]]=a);return d},"o"),e=[6,8,10,12,13,14,15,16,17,18,20,21,22,23,24,25,26,27,28,29,30,31,33,35,36,38,40],n=[1,26],r=[1,27],i=[1,28],g=[1,29],k=[1,30],p=[1,31],_=[1,32],D=[1,33],w=[1,34],I=[1,9],S=[1,10],C=[1,11],G=[1,12],R=[1,13],y=[1,14],E=[1,15],N=[1,16],W=[1,19],H=[1,20],z=[1,21],Y=[1,22],T=[1,23],h=[1,25],$=[1,35],f={trace:l(function(){},"trace"),yy:{},symbols_:{error:2,start:3,gantt:4,document:5,EOF:6,line:7,SPACE:8,statement:9,NL:10,weekday:11,weekday_monday:12,weekday_tuesday:13,weekday_wednesday:14,weekday_thursday:15,weekday_friday:16,weekday_saturday:17,weekday_sunday:18,weekend:19,weekend_friday:20,weekend_saturday:21,dateFormat:22,inclusiveEndDates:23,topAxis:24,axisFormat:25,tickInterval:26,excludes:27,includes:28,todayMarker:29,title:30,acc_title:31,acc_title_value:32,acc_descr:33,acc_descr_value:34,acc_descr_multiline_value:35,section:36,clickStatement:37,taskTxt:38,taskData:39,click:40,callbackname:41,callbackargs:42,href:43,clickStatementDebug:44,$accept:0,$end:1},terminals_:{2:"error",4:"gantt",6:"EOF",8:"SPACE",10:"NL",12:"weekday_monday",13:"weekday_tuesday",14:"weekday_wednesday",15:"weekday_thursday",16:"weekday_friday",17:"weekday_saturday",18:"weekday_sunday",20:"weekend_friday",21:"weekend_saturday",22:"dateFormat",23:"inclusiveEndDates",24:"topAxis",25:"axisFormat",26:"tickInterval",27:"excludes",28:"includes",29:"todayMarker",30:"title",31:"acc_title",32:"acc_title_value",33:"acc_descr",34:"acc_descr_value",35:"acc_descr_multiline_value",36:"section",38:"taskTxt",39:"taskData",40:"click",41:"callbackname",42:"callbackargs",43:"href"},productions_:[0,[3,3],[5,0],[5,2],[7,2],[7,1],[7,1],[7,1],[11,1],[11,1],[11,1],[11,1],[11,1],[11,1],[11,1],[19,1],[19,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,2],[9,2],[9,1],[9,1],[9,1],[9,2],[37,2],[37,3],[37,3],[37,4],[37,3],[37,4],[37,2],[44,2],[44,3],[44,3],[44,4],[44,3],[44,4],[44,2]],performAction:l(function(a,d,m,u,M,s,A){var o=s.length-1;switch(M){case 1:return s[o-1];case 2:this.$=[];break;case 3:s[o-1].push(s[o]),this.$=s[o-1];break;case 4:case 5:this.$=s[o];break;case 6:case 7:this.$=[];break;case 8:u.setWeekday("monday");break;case 9:u.setWeekday("tuesday");break;case 10:u.setWeekday("wednesday");break;case 11:u.setWeekday("thursday");break;case 12:u.setWeekday("friday");break;case 13:u.setWeekday("saturday");break;case 14:u.setWeekday("sunday");break;case 15:u.setWeekend("friday");break;case 16:u.setWeekend("saturday");break;case 17:u.setDateFormat(s[o].substr(11)),this.$=s[o].substr(11);break;case 18:u.enableInclusiveEndDates(),this.$=s[o].substr(18);break;case 19:u.TopAxis(),this.$=s[o].substr(8);break;case 20:u.setAxisFormat(s[o].substr(11)),this.$=s[o].substr(11);break;case 21:u.setTickInterval(s[o].substr(13)),this.$=s[o].substr(13);break;case 22:u.setExcludes(s[o].substr(9)),this.$=s[o].substr(9);break;case 23:u.setIncludes(s[o].substr(9)),this.$=s[o].substr(9);break;case 24:u.setTodayMarker(s[o].substr(12)),this.$=s[o].substr(12);break;case 27:u.setDiagramTitle(s[o].substr(6)),this.$=s[o].substr(6);break;case 28:this.$=s[o].trim(),u.setAccTitle(this.$);break;case 29:case 30:this.$=s[o].trim(),u.setAccDescription(this.$);break;case 31:u.addSection(s[o].substr(8)),this.$=s[o].substr(8);break;case 33:u.addTask(s[o-1],s[o]),this.$="task";break;case 34:this.$=s[o-1],u.setClickEvent(s[o-1],s[o],null);break;case 35:this.$=s[o-2],u.setClickEvent(s[o-2],s[o-1],s[o]);break;case 36:this.$=s[o-2],u.setClickEvent(s[o-2],s[o-1],null),u.setLink(s[o-2],s[o]);break;case 37:this.$=s[o-3],u.setClickEvent(s[o-3],s[o-2],s[o-1]),u.setLink(s[o-3],s[o]);break;case 38:this.$=s[o-2],u.setClickEvent(s[o-2],s[o],null),u.setLink(s[o-2],s[o-1]);break;case 39:this.$=s[o-3],u.setClickEvent(s[o-3],s[o-1],s[o]),u.setLink(s[o-3],s[o-2]);break;case 40:this.$=s[o-1],u.setLink(s[o-1],s[o]);break;case 41:case 47:this.$=s[o-1]+" "+s[o];break;case 42:case 43:case 45:this.$=s[o-2]+" "+s[o-1]+" "+s[o];break;case 44:case 46:this.$=s[o-3]+" "+s[o-2]+" "+s[o-1]+" "+s[o];break}},"anonymous"),table:[{3:1,4:[1,2]},{1:[3]},t(e,[2,2],{5:3}),{6:[1,4],7:5,8:[1,6],9:7,10:[1,8],11:17,12:n,13:r,14:i,15:g,16:k,17:p,18:_,19:18,20:D,21:w,22:I,23:S,24:C,25:G,26:R,27:y,28:E,29:N,30:W,31:H,33:z,35:Y,36:T,37:24,38:h,40:$},t(e,[2,7],{1:[2,1]}),t(e,[2,3]),{9:36,11:17,12:n,13:r,14:i,15:g,16:k,17:p,18:_,19:18,20:D,21:w,22:I,23:S,24:C,25:G,26:R,27:y,28:E,29:N,30:W,31:H,33:z,35:Y,36:T,37:24,38:h,40:$},t(e,[2,5]),t(e,[2,6]),t(e,[2,17]),t(e,[2,18]),t(e,[2,19]),t(e,[2,20]),t(e,[2,21]),t(e,[2,22]),t(e,[2,23]),t(e,[2,24]),t(e,[2,25]),t(e,[2,26]),t(e,[2,27]),{32:[1,37]},{34:[1,38]},t(e,[2,30]),t(e,[2,31]),t(e,[2,32]),{39:[1,39]},t(e,[2,8]),t(e,[2,9]),t(e,[2,10]),t(e,[2,11]),t(e,[2,12]),t(e,[2,13]),t(e,[2,14]),t(e,[2,15]),t(e,[2,16]),{41:[1,40],43:[1,41]},t(e,[2,4]),t(e,[2,28]),t(e,[2,29]),t(e,[2,33]),t(e,[2,34],{42:[1,42],43:[1,43]}),t(e,[2,40],{41:[1,44]}),t(e,[2,35],{43:[1,45]}),t(e,[2,36]),t(e,[2,38],{42:[1,46]}),t(e,[2,37]),t(e,[2,39])],defaultActions:{},parseError:l(function(a,d){if(d.recoverable)this.trace(a);else{var m=new Error(a);throw m.hash=d,m}},"parseError"),parse:l(function(a){var d=this,m=[0],u=[],M=[null],s=[],A=this.table,o="",q=0,c=0,F=2,L=1,V=s.slice.call(arguments,1),O=Object.create(this.lexer),B={yy:{}};for(var P in this.yy)Object.prototype.hasOwnProperty.call(this.yy,P)&&(B.yy[P]=this.yy[P]);O.setInput(a,B.yy),B.yy.lexer=O,B.yy.parser=this,typeof O.yylloc>"u"&&(O.yylloc={});var nt=O.yylloc;s.push(nt);var st=O.options&&O.options.ranges;typeof B.yy.parseError=="function"?this.parseError=B.yy.parseError:this.parseError=Object.getPrototypeOf(this).parseError;function yt(Q){m.length=m.length-2*Q,M.length=M.length-Q,s.length=s.length-Q}l(yt,"popStack");function lt(){var Q;return Q=u.pop()||O.lex()||L,typeof Q!="number"&&(Q instanceof Array&&(u=Q,Q=u.pop()),Q=d.symbols_[Q]||Q),Q}l(lt,"lex");for(var X,K,Z,at,J={},it,tt,Zt,pt;;){if(K=m[m.length-1],this.defaultActions[K]?Z=this.defaultActions[K]:((X===null||typeof X>"u")&&(X=lt()),Z=A[K]&&A[K][X]),typeof Z>"u"||!Z.length||!Z[0]){var Yt="";pt=[];for(it in A[K])this.terminals_[it]&&it>F&&pt.push("'"+this.terminals_[it]+"'");O.showPosition?Yt="Parse error on line "+(q+1)+`:
`+O.showPosition()+`
Expecting `+pt.join(", ")+", got '"+(this.terminals_[X]||X)+"'":Yt="Parse error on line "+(q+1)+": Unexpected "+(X==L?"end of input":"'"+(this.terminals_[X]||X)+"'"),this.parseError(Yt,{text:O.match,token:this.terminals_[X]||X,line:O.yylineno,loc:nt,expected:pt})}if(Z[0]instanceof Array&&Z.length>1)throw new Error("Parse Error: multiple actions possible at state: "+K+", token: "+X);switch(Z[0]){case 1:m.push(X),M.push(O.yytext),s.push(O.yylloc),m.push(Z[1]),X=null,c=O.yyleng,o=O.yytext,q=O.yylineno,nt=O.yylloc;break;case 2:if(tt=this.productions_[Z[1]][1],J.$=M[M.length-tt],J._$={first_line:s[s.length-(tt||1)].first_line,last_line:s[s.length-1].last_line,first_column:s[s.length-(tt||1)].first_column,last_column:s[s.length-1].last_column},st&&(J._$.range=[s[s.length-(tt||1)].range[0],s[s.length-1].range[1]]),at=this.performAction.apply(J,[o,c,q,B.yy,Z[1],M,s].concat(V)),typeof at<"u")return at;tt&&(m=m.slice(0,-1*tt*2),M=M.slice(0,-1*tt),s=s.slice(0,-1*tt)),m.push(this.productions_[Z[1]][0]),M.push(J.$),s.push(J._$),Zt=A[m[m.length-2]][m[m.length-1]],m.push(Zt);break;case 3:return!0}}return!0},"parse")},b=(function(){var v={EOF:1,parseError:l(function(d,m){if(this.yy.parser)this.yy.parser.parseError(d,m);else throw new Error(d)},"parseError"),setInput:l(function(a,d){return this.yy=d||this.yy||{},this._input=a,this._more=this._backtrack=this.done=!1,this.yylineno=this.yyleng=0,this.yytext=this.matched=this.match="",this.conditionStack=["INITIAL"],this.yylloc={first_line:1,first_column:0,last_line:1,last_column:0},this.options.ranges&&(this.yylloc.range=[0,0]),this.offset=0,this},"setInput"),input:l(function(){var a=this._input[0];this.yytext+=a,this.yyleng++,this.offset++,this.match+=a,this.matched+=a;var d=a.match(/(?:\r\n?|\n).*/g);return d?(this.yylineno++,this.yylloc.last_line++):this.yylloc.last_column++,this.options.ranges&&this.yylloc.range[1]++,this._input=this._input.slice(1),a},"input"),unput:l(function(a){var d=a.length,m=a.split(/(?:\r\n?|\n)/g);this._input=a+this._input,this.yytext=this.yytext.substr(0,this.yytext.length-d),this.offset-=d;var u=this.match.split(/(?:\r\n?|\n)/g);this.match=this.match.substr(0,this.match.length-1),this.matched=this.matched.substr(0,this.matched.length-1),m.length-1&&(this.yylineno-=m.length-1);var M=this.yylloc.range;return this.yylloc={first_line:this.yylloc.first_line,last_line:this.yylineno+1,first_column:this.yylloc.first_column,last_column:m?(m.length===u.length?this.yylloc.first_column:0)+u[u.length-m.length].length-m[0].length:this.yylloc.first_column-d},this.options.ranges&&(this.yylloc.range=[M[0],M[0]+this.yyleng-d]),this.yyleng=this.yytext.length,this},"unput"),more:l(function(){return this._more=!0,this},"more"),reject:l(function(){if(this.options.backtrack_lexer)this._backtrack=!0;else return this.parseError("Lexical error on line "+(this.yylineno+1)+`. You can only invoke reject() in the lexer when the lexer is of the backtracking persuasion (options.backtrack_lexer = true).
`+this.showPosition(),{text:"",token:null,line:this.yylineno});return this},"reject"),less:l(function(a){this.unput(this.match.slice(a))},"less"),pastInput:l(function(){var a=this.matched.substr(0,this.matched.length-this.match.length);return(a.length>20?"...":"")+a.substr(-20).replace(/\n/g,"")},"pastInput"),upcomingInput:l(function(){var a=this.match;return a.length<20&&(a+=this._input.substr(0,20-a.length)),(a.substr(0,20)+(a.length>20?"...":"")).replace(/\n/g,"")},"upcomingInput"),showPosition:l(function(){var a=this.pastInput(),d=new Array(a.length+1).join("-");return a+this.upcomingInput()+`
`+d+"^"},"showPosition"),test_match:l(function(a,d){var m,u,M;if(this.options.backtrack_lexer&&(M={yylineno:this.yylineno,yylloc:{first_line:this.yylloc.first_line,last_line:this.last_line,first_column:this.yylloc.first_column,last_column:this.yylloc.last_column},yytext:this.yytext,match:this.match,matches:this.matches,matched:this.matched,yyleng:this.yyleng,offset:this.offset,_more:this._more,_input:this._input,yy:this.yy,conditionStack:this.conditionStack.slice(0),done:this.done},this.options.ranges&&(M.yylloc.range=this.yylloc.range.slice(0))),u=a[0].match(/(?:\r\n?|\n).*/g),u&&(this.yylineno+=u.length),this.yylloc={first_line:this.yylloc.last_line,last_line:this.yylineno+1,first_column:this.yylloc.last_column,last_column:u?u[u.length-1].length-u[u.length-1].match(/\r?\n?/)[0].length:this.yylloc.last_column+a[0].length},this.yytext+=a[0],this.match+=a[0],this.matches=a,this.yyleng=this.yytext.length,this.options.ranges&&(this.yylloc.range=[this.offset,this.offset+=this.yyleng]),this._more=!1,this._backtrack=!1,this._input=this._input.slice(a[0].length),this.matched+=a[0],m=this.performAction.call(this,this.yy,this,d,this.conditionStack[this.conditionStack.length-1]),this.done&&this._input&&(this.done=!1),m)return m;if(this._backtrack){for(var s in M)this[s]=M[s];return!1}return!1},"test_match"),next:l(function(){if(this.done)return this.EOF;this._input||(this.done=!0);var a,d,m,u;this._more||(this.yytext="",this.match="");for(var M=this._currentRules(),s=0;s<M.length;s++)if(m=this._input.match(this.rules[M[s]]),m&&(!d||m[0].length>d[0].length)){if(d=m,u=s,this.options.backtrack_lexer){if(a=this.test_match(m,M[s]),a!==!1)return a;if(this._backtrack){d=!1;continue}else return!1}else if(!this.options.flex)break}return d?(a=this.test_match(d,M[u]),a!==!1?a:!1):this._input===""?this.EOF:this.parseError("Lexical error on line "+(this.yylineno+1)+`. Unrecognized text.
`+this.showPosition(),{text:"",token:null,line:this.yylineno})},"next"),lex:l(function(){var d=this.next();return d||this.lex()},"lex"),begin:l(function(d){this.conditionStack.push(d)},"begin"),popState:l(function(){var d=this.conditionStack.length-1;return d>0?this.conditionStack.pop():this.conditionStack[0]},"popState"),_currentRules:l(function(){return this.conditionStack.length&&this.conditionStack[this.conditionStack.length-1]?this.conditions[this.conditionStack[this.conditionStack.length-1]].rules:this.conditions.INITIAL.rules},"_currentRules"),topState:l(function(d){return d=this.conditionStack.length-1-Math.abs(d||0),d>=0?this.conditionStack[d]:"INITIAL"},"topState"),pushState:l(function(d){this.begin(d)},"pushState"),stateStackSize:l(function(){return this.conditionStack.length},"stateStackSize"),options:{"case-insensitive":!0},performAction:l(function(d,m,u,M){switch(u){case 0:return this.begin("open_directive"),"open_directive";case 1:return this.begin("acc_title"),31;case 2:return this.popState(),"acc_title_value";case 3:return this.begin("acc_descr"),33;case 4:return this.popState(),"acc_descr_value";case 5:this.begin("acc_descr_multiline");break;case 6:this.popState();break;case 7:return"acc_descr_multiline_value";case 8:break;case 9:break;case 10:break;case 11:return 10;case 12:break;case 13:break;case 14:this.begin("href");break;case 15:this.popState();break;case 16:return 43;case 17:this.begin("callbackname");break;case 18:this.popState();break;case 19:this.popState(),this.begin("callbackargs");break;case 20:return 41;case 21:this.popState();break;case 22:return 42;case 23:this.begin("click");break;case 24:this.popState();break;case 25:return 40;case 26:return 4;case 27:return 22;case 28:return 23;case 29:return 24;case 30:return 25;case 31:return 26;case 32:return 28;case 33:return 27;case 34:return 29;case 35:return 12;case 36:return 13;case 37:return 14;case 38:return 15;case 39:return 16;case 40:return 17;case 41:return 18;case 42:return 20;case 43:return 21;case 44:return"date";case 45:return 30;case 46:return"accDescription";case 47:return 36;case 48:return 38;case 49:return 39;case 50:return":";case 51:return 6;case 52:return"INVALID"}},"anonymous"),rules:[/^(?:%%\{)/i,/^(?:accTitle\s*:\s*)/i,/^(?:(?!\n||)*[^\n]*)/i,/^(?:accDescr\s*:\s*)/i,/^(?:(?!\n||)*[^\n]*)/i,/^(?:accDescr\s*\{\s*)/i,/^(?:[\}])/i,/^(?:[^\}]*)/i,/^(?:%%(?!\{)*[^\n]*)/i,/^(?:[^\}]%%*[^\n]*)/i,/^(?:%%*[^\n]*[\n]*)/i,/^(?:[\n]+)/i,/^(?:\s+)/i,/^(?:%[^\n]*)/i,/^(?:href[\s]+["])/i,/^(?:["])/i,/^(?:[^"]*)/i,/^(?:call[\s]+)/i,/^(?:\([\s]*\))/i,/^(?:\()/i,/^(?:[^(]*)/i,/^(?:\))/i,/^(?:[^)]*)/i,/^(?:click[\s]+)/i,/^(?:[\s\n])/i,/^(?:[^\s\n]*)/i,/^(?:gantt\b)/i,/^(?:dateFormat\s[^#\n;]+)/i,/^(?:inclusiveEndDates\b)/i,/^(?:topAxis\b)/i,/^(?:axisFormat\s[^#\n;]+)/i,/^(?:tickInterval\s[^#\n;]+)/i,/^(?:includes\s[^#\n;]+)/i,/^(?:excludes\s[^#\n;]+)/i,/^(?:todayMarker\s[^\n;]+)/i,/^(?:weekday\s+monday\b)/i,/^(?:weekday\s+tuesday\b)/i,/^(?:weekday\s+wednesday\b)/i,/^(?:weekday\s+thursday\b)/i,/^(?:weekday\s+friday\b)/i,/^(?:weekday\s+saturday\b)/i,/^(?:weekday\s+sunday\b)/i,/^(?:weekend\s+friday\b)/i,/^(?:weekend\s+saturday\b)/i,/^(?:\d\d\d\d-\d\d-\d\d\b)/i,/^(?:title\s[^\n]+)/i,/^(?:accDescription\s[^#\n;]+)/i,/^(?:section\s[^\n]+)/i,/^(?:[^:\n]+)/i,/^(?::[^#\n;]+)/i,/^(?::)/i,/^(?:$)/i,/^(?:.)/i],conditions:{acc_descr_multiline:{rules:[6,7],inclusive:!1},acc_descr:{rules:[4],inclusive:!1},acc_title:{rules:[2],inclusive:!1},callbackargs:{rules:[21,22],inclusive:!1},callbackname:{rules:[18,19,20],inclusive:!1},href:{rules:[15,16],inclusive:!1},click:{rules:[24,25],inclusive:!1},INITIAL:{rules:[0,1,3,5,8,9,10,11,12,13,14,17,23,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52],inclusive:!0}}};return v})();f.lexer=b;function x(){this.yy={}}return l(x,"Parser"),x.prototype=f,f.Parser=x,new x})();Ot.parser=Ot;var vr=Ot;U.extend(ar);U.extend(ur);U.extend(mr);var le={friday:5,saturday:6},et="",Vt="",zt=void 0,Rt="",ht=[],mt=[],Ht=new Map,Bt=[],Et=[],kt="",qt="",me=["active","done","crit","milestone","vert"],Gt=[],ut="",gt=!1,Xt=!1,jt="sunday",It="saturday",Wt=0,xr=l(function(){Bt=[],Et=[],kt="",Gt=[],Ct=0,Pt=void 0,Mt=void 0,j=[],et="",Vt="",qt="",zt=void 0,Rt="",ht=[],mt=[],gt=!1,Xt=!1,Wt=0,Ht=new Map,ut="",Ye(),jt="sunday",It="saturday"},"clear"),Tr=l(function(t){ut=t},"setDiagramId"),br=l(function(t){Vt=t},"setAxisFormat"),wr=l(function(){return Vt},"getAxisFormat"),_r=l(function(t){zt=t},"setTickInterval"),Dr=l(function(){return zt},"getTickInterval"),Sr=l(function(t){Rt=t},"setTodayMarker"),Cr=l(function(){return Rt},"getTodayMarker"),Mr=l(function(t){et=t},"setDateFormat"),Er=l(function(){gt=!0},"enableInclusiveEndDates"),Ir=l(function(){return gt},"endDatesAreInclusive"),$r=l(function(){Xt=!0},"enableTopAxis"),Yr=l(function(){return Xt},"topAxisEnabled"),Ar=l(function(t){qt=t},"setDisplayMode"),Fr=l(function(){return qt},"getDisplayMode"),Lr=l(function(){return et},"getDateFormat"),ke=l((t,e)=>{const n=e.toLowerCase().split(/[\s,]+/).filter(r=>r!=="");return[...new Set([...t,...n])]},"mergeTokens"),Or=l(function(t){ht=ke(ht,t)},"setIncludes"),Wr=l(function(){return ht},"getIncludes"),Nr=l(function(t){mt=ke(mt,t)},"setExcludes"),Pr=l(function(){return mt},"getExcludes"),Vr=l(function(){return Ht},"getLinks"),zr=l(function(t){kt=t,Bt.push(t)},"addSection"),Rr=l(function(){return Bt},"getSections"),Hr=l(function(){let t=ue();const e=10;let n=0;for(;!t&&n<e;)t=ue(),n++;return Et=j,Et},"getTasks"),ye=l(function(t,e,n,r){const i=t.format(e.trim()),g=t.format("YYYY-MM-DD");return r.includes(i)||r.includes(g)?!1:n.includes("weekends")&&(t.isoWeekday()===le[It]||t.isoWeekday()===le[It]+1)||n.includes(t.format("dddd").toLowerCase())?!0:n.includes(i)||n.includes(g)},"isInvalidDate"),Br=l(function(t){jt=t},"setWeekday"),qr=l(function(){return jt},"getWeekday"),Gr=l(function(t){It=t},"setWeekend"),ge=l(function(t,e,n,r){if(!n.length||t.manualEndTime)return;let i;t.startTime instanceof Date?i=U(t.startTime):i=U(t.startTime,e,!0),i=i.add(1,"d");let g;t.endTime instanceof Date?g=U(t.endTime):g=U(t.endTime,e,!0);const[k,p]=Xr(i,g,e,n,r);t.endTime=k.toDate(),t.renderEndTime=p},"checkTaskDates"),Xr=l(function(t,e,n,r,i){let g=!1,k=null;const p=e.add(1e4,"d");for(;t<=e;){if(g||(k=e.toDate()),g=ye(t,n,r,i),g&&(e=e.add(1,"d"),e>p))throw new Error("Failed to find a valid date that was not excluded by `excludes` after 10,000 iterations.");t=t.add(1,"d")}return[e,k]},"fixTaskDates"),Nt=l(function(t,e,n){if(n=n.trim(),l(p=>{const _=p.trim();return _==="x"||_==="X"},"isTimestampFormat")(e)&&/^\d+$/.test(n))return new Date(Number(n));const g=/^after\s+(?<ids>[\d\w- ]+)/.exec(n);if(g!==null){let p=null;for(const D of g.groups.ids.split(" ")){let w=ct(D);w!==void 0&&(!p||w.endTime>p.endTime)&&(p=w)}if(p)return p.endTime;const _=new Date;return _.setHours(0,0,0,0),_}let k=U(n,e.trim(),!0);if(k.isValid())return k.toDate();{ot.debug("Invalid date:"+n),ot.debug("With date format:"+e.trim());const p=new Date(n);if(p===void 0||isNaN(p.getTime())||p.getFullYear()<-1e4||p.getFullYear()>1e4)throw new Error("Invalid date:"+n);return p}},"getStartDate"),pe=l(function(t){const e=/^(\d+(?:\.\d+)?)([Mdhmswy]|ms)$/.exec(t.trim());return e!==null?[Number.parseFloat(e[1]),e[2]]:[NaN,"ms"]},"parseDuration"),ve=l(function(t,e,n,r=!1){n=n.trim();const g=/^until\s+(?<ids>[\d\w- ]+)/.exec(n);if(g!==null){let w=null;for(const S of g.groups.ids.split(" ")){let C=ct(S);C!==void 0&&(!w||C.startTime<w.startTime)&&(w=C)}if(w)return w.startTime;const I=new Date;return I.setHours(0,0,0,0),I}let k=U(n,e.trim(),!0);if(k.isValid())return r&&(k=k.add(1,"d")),k.toDate();let p=U(t);const[_,D]=pe(n);if(!Number.isNaN(_)){const w=p.add(_,D);w.isValid()&&(p=w)}return p.toDate()},"getEndDate"),Ct=0,ft=l(function(t){return t===void 0?(Ct=Ct+1,"task"+Ct):t},"parseId"),jr=l(function(t,e){let n;e.substr(0,1)===":"?n=e.substr(1,e.length):n=e;const r=n.split(","),i={};Ut(r,i,me);for(let k=0;k<r.length;k++)r[k]=r[k].trim();let g="";switch(r.length){case 1:i.id=ft(),i.startTime=t.endTime,g=r[0];break;case 2:i.id=ft(),i.startTime=Nt(void 0,et,r[0]),g=r[1];break;case 3:i.id=ft(r[0]),i.startTime=Nt(void 0,et,r[1]),g=r[2];break}return g&&(i.endTime=ve(i.startTime,et,g,gt),i.manualEndTime=U(g,"YYYY-MM-DD",!0).isValid(),ge(i,et,mt,ht)),i},"compileData"),Ur=l(function(t,e){let n;e.substr(0,1)===":"?n=e.substr(1,e.length):n=e;const r=n.split(","),i={};Ut(r,i,me);for(let g=0;g<r.length;g++)r[g]=r[g].trim();switch(r.length){case 1:i.id=ft(),i.startTime={type:"prevTaskEnd",id:t},i.endTime={data:r[0]};break;case 2:i.id=ft(),i.startTime={type:"getStartDate",startData:r[0]},i.endTime={data:r[1]};break;case 3:i.id=ft(r[0]),i.startTime={type:"getStartDate",startData:r[1]},i.endTime={data:r[2]};break}return i},"parseData"),Pt,Mt,j=[],xe={},Zr=l(function(t,e){const n={section:kt,type:kt,processed:!1,manualEndTime:!1,renderEndTime:null,raw:{data:e},task:t,classes:[]},r=Ur(Mt,e);n.raw.startTime=r.startTime,n.raw.endTime=r.endTime,n.id=r.id,n.prevTaskId=Mt,n.active=r.active,n.done=r.done,n.crit=r.crit,n.milestone=r.milestone,n.vert=r.vert,n.vert?n.order=-1:(n.order=Wt,Wt++);const i=j.push(n);Mt=n.id,xe[n.id]=i-1},"addTask"),ct=l(function(t){const e=xe[t];return j[e]},"findTaskById"),Qr=l(function(t,e){const n={section:kt,type:kt,description:t,task:t,classes:[]},r=jr(Pt,e);n.startTime=r.startTime,n.endTime=r.endTime,n.id=r.id,n.active=r.active,n.done=r.done,n.crit=r.crit,n.milestone=r.milestone,n.vert=r.vert,Pt=n,Et.push(n)},"addTaskOrg"),ue=l(function(){const t=l(function(n){const r=j[n];let i="";switch(j[n].raw.startTime.type){case"prevTaskEnd":{const g=ct(r.prevTaskId);r.startTime=g.endTime;break}case"getStartDate":i=Nt(void 0,et,j[n].raw.startTime.startData),i&&(j[n].startTime=i);break}return j[n].startTime&&(j[n].endTime=ve(j[n].startTime,et,j[n].raw.endTime.data,gt),j[n].endTime&&(j[n].processed=!0,j[n].manualEndTime=U(j[n].raw.endTime.data,"YYYY-MM-DD",!0).isValid(),ge(j[n],et,mt,ht))),j[n].processed},"compileTask");let e=!0;for(const[n,r]of j.entries())t(n),e=e&&r.processed;return e},"compileTasks"),Kr=l(function(t,e){let n=e;dt().securityLevel!=="loose"&&(n=$e.sanitizeUrl(e)),t.split(",").forEach(function(r){ct(r)!==void 0&&(be(r,()=>{window.open(n,"_self")}),Ht.set(r,n))}),Te(t,"clickable")},"setLink"),Te=l(function(t,e){t.split(",").forEach(function(n){let r=ct(n);r!==void 0&&r.classes.push(e)})},"setClass"),Jr=l(function(t,e,n){if(dt().securityLevel!=="loose"||e===void 0)return;let r=[];if(typeof n=="string"){r=n.split(/,(?=(?:(?:[^"]*"){2})*[^"]*$)/);for(let g=0;g<r.length;g++){let k=r[g].trim();k.startsWith('"')&&k.endsWith('"')&&(k=k.substr(1,k.length-2)),r[g]=k}}r.length===0&&r.push(t),ct(t)!==void 0&&be(t,()=>{Ae.runFunc(e,...r)})},"setClickFun"),be=l(function(t,e){Gt.push(function(){const n=ut?`${ut}-${t}`:t,r=document.querySelector(`[id="${n}"]`);r!==null&&r.addEventListener("click",function(){e()})},function(){const n=ut?`${ut}-${t}`:t,r=document.querySelector(`[id="${n}-text"]`);r!==null&&r.addEventListener("click",function(){e()})})},"pushFun"),tn=l(function(t,e,n){t.split(",").forEach(function(r){Jr(r,e,n)}),Te(t,"clickable")},"setClickEvent"),en=l(function(t){Gt.forEach(function(e){e(t)})},"bindFunctions"),rn={getConfig:l(()=>dt().gantt,"getConfig"),clear:xr,setDateFormat:Mr,getDateFormat:Lr,enableInclusiveEndDates:Er,endDatesAreInclusive:Ir,enableTopAxis:$r,topAxisEnabled:Yr,setAxisFormat:br,getAxisFormat:wr,setTickInterval:_r,getTickInterval:Dr,setTodayMarker:Sr,getTodayMarker:Cr,setAccTitle:Me,getAccTitle:Ce,setDiagramTitle:Se,getDiagramTitle:De,setDiagramId:Tr,setDisplayMode:Ar,getDisplayMode:Fr,setAccDescription:_e,getAccDescription:we,addSection:zr,getSections:Rr,getTasks:Hr,addTask:Zr,findTaskById:ct,addTaskOrg:Qr,setIncludes:Or,getIncludes:Wr,setExcludes:Nr,getExcludes:Pr,setClickEvent:tn,setLink:Kr,getLinks:Vr,bindFunctions:en,parseDuration:pe,isInvalidDate:ye,setWeekday:Br,getWeekday:qr,setWeekend:Gr};function Ut(t,e,n){let r=!0;for(;r;)r=!1,n.forEach(function(i){const g="^\\s*"+i+"\\s*$",k=new RegExp(g);t[0].match(k)&&(e[i]=!0,t.shift(1),r=!0)})}l(Ut,"getTaskTags");U.extend(pr);var nn=l(function(){ot.debug("Something is calling, setConf, remove the call")},"setConf"),de={monday:Re,tuesday:ze,wednesday:Ve,thursday:Pe,friday:Ne,saturday:We,sunday:Oe},sn=l((t,e)=>{let n=[...t].map(()=>-1/0),r=[...t].sort((g,k)=>g.startTime-k.startTime||g.order-k.order),i=0;for(const g of r)for(let k=0;k<n.length;k++)if(g.startTime>=n[k]){n[k]=g.endTime,g.order=k+e,k>i&&(i=k);break}return i},"getMaxIntersections"),rt,Ft=1e4,an=l(function(t,e,n,r){const i=dt().gantt;r.db.setDiagramId(e);const g=dt().securityLevel;let k;g==="sandbox"&&(k=vt("#i"+e));const p=g==="sandbox"?vt(k.nodes()[0].contentDocument.body):vt("body"),_=g==="sandbox"?k.nodes()[0].contentDocument:document,D=_.getElementById(e);rt=D.parentElement.offsetWidth,rt===void 0&&(rt=1200),i.useWidth!==void 0&&(rt=i.useWidth);const w=r.db.getTasks(),I=w.filter(f=>!f.vert);let S=[];for(const f of I)S.push(f.type);S=$(S);const C={};let G=2*i.topPadding;if(r.db.getDisplayMode()==="compact"||i.displayMode==="compact"){const f={};for(const x of I)f[x.section]===void 0?f[x.section]=[x]:f[x.section].push(x);let b=0;for(const x of Object.keys(f)){const v=sn(f[x],b)+1;b+=v,G+=v*(i.barHeight+i.barGap),C[x]=v}}else{G+=I.length*(i.barHeight+i.barGap);for(const f of S)C[f]=I.filter(b=>b.type===f).length}D.setAttribute("viewBox","0 0 "+rt+" "+G);const R=p.select(`[id="${e}"]`),y=Fe().domain([je(w,function(f){return f.startTime}),Xe(w,function(f){return f.endTime})]).rangeRound([0,rt-i.leftPadding-i.rightPadding]);function E(f,b){const x=f.startTime,v=b.startTime;let a=0;return x>v?a=1:x<v&&(a=-1),a}l(E,"taskCompare"),w.sort(E),N(w,rt,G),Ee(R,G,rt,i.useMaxWidth),R.append("text").text(r.db.getDiagramTitle()).attr("x",rt/2).attr("y",i.titleTopMargin).attr("class","titleText");function N(f,b,x){const v=i.barHeight,a=v+i.barGap,d=i.topPadding,m=i.leftPadding,u=Le().domain([0,S.length]).range(["#00B9FA","#F95002"]).interpolate(He);H(a,d,m,b,x,f,r.db.getExcludes(),r.db.getIncludes()),Y(m,d,b,x),W(f,a,d,m,v,u,b),T(a,d),h(m,d,b,x)}l(N,"makeGantt");function W(f,b,x,v,a,d,m){f.sort((c,F)=>c.vert===F.vert?0:c.vert?1:-1);const u=f.filter(c=>!c.vert),s=[...new Set(u.map(c=>c.order))].map(c=>u.find(F=>F.order===c));R.append("g").selectAll("rect").data(s).enter().append("rect").attr("x",0).attr("y",function(c,F){return F=c.order,F*b+x-2}).attr("width",function(){return m-i.rightPadding/2}).attr("height",b).attr("class",function(c){for(const[F,L]of S.entries())if(c.type===L)return"section section"+F%i.numberSectionStyles;return"section section0"}).enter();const A=R.append("g").selectAll("rect").data(f).enter(),o=r.db.getLinks();if(A.append("rect").attr("id",function(c){return e+"-"+c.id}).attr("rx",3).attr("ry",3).attr("x",function(c){return c.milestone?y(c.startTime)+v+.5*(y(c.endTime)-y(c.startTime))-.5*a:y(c.startTime)+v}).attr("y",function(c,F){return F=c.order,c.vert?i.gridLineStartPadding:F*b+x}).attr("width",function(c){return c.milestone?a:c.vert?.08*a:y(c.renderEndTime||c.endTime)-y(c.startTime)}).attr("height",function(c){return c.vert?u.length*(i.barHeight+i.barGap)+i.barHeight*2:a}).attr("transform-origin",function(c,F){return F=c.order,(y(c.startTime)+v+.5*(y(c.endTime)-y(c.startTime))).toString()+"px "+(F*b+x+.5*a).toString()+"px"}).attr("class",function(c){const F="task";let L="";c.classes.length>0&&(L=c.classes.join(" "));let V=0;for(const[B,P]of S.entries())c.type===P&&(V=B%i.numberSectionStyles);let O="";return c.active?c.crit?O+=" activeCrit":O=" active":c.done?c.crit?O=" doneCrit":O=" done":c.crit&&(O+=" crit"),O.length===0&&(O=" task"),c.milestone&&(O=" milestone "+O),c.vert&&(O=" vert "+O),O+=V,O+=" "+L,F+O}),A.append("text").attr("id",function(c){return e+"-"+c.id+"-text"}).text(function(c){return c.task}).attr("font-size",i.fontSize).attr("x",function(c){let F=y(c.startTime),L=y(c.renderEndTime||c.endTime);if(c.milestone&&(F+=.5*(y(c.endTime)-y(c.startTime))-.5*a,L=F+a),c.vert)return y(c.startTime)+v;const V=this.getBBox().width;return V>L-F?L+V+1.5*i.leftPadding>m?F+v-5:L+v+5:(L-F)/2+F+v}).attr("y",function(c,F){return c.vert?i.gridLineStartPadding+u.length*(i.barHeight+i.barGap)+60:(F=c.order,F*b+i.barHeight/2+(i.fontSize/2-2)+x)}).attr("text-height",a).attr("class",function(c){const F=y(c.startTime);let L=y(c.endTime);c.milestone&&(L=F+a);const V=this.getBBox().width;let O="";c.classes.length>0&&(O=c.classes.join(" "));let B=0;for(const[nt,st]of S.entries())c.type===st&&(B=nt%i.numberSectionStyles);let P="";return c.active&&(c.crit?P="activeCritText"+B:P="activeText"+B),c.done?c.crit?P=P+" doneCritText"+B:P=P+" doneText"+B:c.crit&&(P=P+" critText"+B),c.milestone&&(P+=" milestoneText"),c.vert&&(P+=" vertText"),V>L-F?L+V+1.5*i.leftPadding>m?O+" taskTextOutsideLeft taskTextOutside"+B+" "+P:O+" taskTextOutsideRight taskTextOutside"+B+" "+P+" width-"+V:O+" taskText taskText"+B+" "+P+" width-"+V}),dt().securityLevel==="sandbox"){let c;c=vt("#i"+e);const F=c.nodes()[0].contentDocument;A.filter(function(L){return o.has(L.id)}).each(function(L){var V=F.querySelector("#"+CSS.escape(e+"-"+L.id)),O=F.querySelector("#"+CSS.escape(e+"-"+L.id+"-text"));const B=V.parentNode;var P=F.createElement("a");P.setAttribute("xlink:href",o.get(L.id)),P.setAttribute("target","_top"),B.appendChild(P),P.appendChild(V),P.appendChild(O)})}}l(W,"drawRects");function H(f,b,x,v,a,d,m,u){if(m.length===0&&u.length===0)return;let M,s;for(const{startTime:L,endTime:V}of d)(M===void 0||L<M)&&(M=L),(s===void 0||V>s)&&(s=V);if(!M||!s)return;if(U(s).diff(U(M),"year")>5){ot.warn("The difference between the min and max time is more than 5 years. This will cause performance issues. Skipping drawing exclude days.");return}const A=r.db.getDateFormat(),o=[];let q=null,c=U(M);for(;c.valueOf()<=s;)r.db.isInvalidDate(c,A,m,u)?q?q.end=c:q={start:c,end:c}:q&&(o.push(q),q=null),c=c.add(1,"d");R.append("g").selectAll("rect").data(o).enter().append("rect").attr("id",L=>e+"-exclude-"+L.start.format("YYYY-MM-DD")).attr("x",L=>y(L.start.startOf("day"))+x).attr("y",i.gridLineStartPadding).attr("width",L=>y(L.end.endOf("day"))-y(L.start.startOf("day"))).attr("height",a-b-i.gridLineStartPadding).attr("transform-origin",function(L,V){return(y(L.start)+x+.5*(y(L.end)-y(L.start))).toString()+"px "+(V*f+.5*a).toString()+"px"}).attr("class","exclude-range")}l(H,"drawExcludeDays");function z(f,b,x,v){if(x<=0||f>b)return 1/0;const a=b-f,d=U.duration({[v??"day"]:x}).asMilliseconds();return d<=0?1/0:Math.ceil(a/d)}l(z,"getEstimatedTickCount");function Y(f,b,x,v){const a=r.db.getDateFormat(),d=r.db.getAxisFormat();let m;d?m=d:a==="D"?m="%d":m=i.axisFormat??"%Y-%m-%d";let u=rr(y).tickSize(-v+b+i.gridLineStartPadding).tickFormat(Qt(m));const s=/^([1-9]\d*)(millisecond|second|minute|hour|day|week|month)$/.exec(r.db.getTickInterval()||i.tickInterval);if(s!==null){const A=parseInt(s[1],10);if(isNaN(A)||A<=0)ot.warn(`Invalid tick interval value: "${s[1]}". Skipping custom tick interval.`);else{const o=s[2],q=r.db.getWeekday()||i.weekday,c=y.domain(),F=c[0],L=c[1],V=z(F,L,A,o);if(V>Ft)ot.warn(`The tick interval "${A}${o}" would generate ${V} ticks, which exceeds the maximum allowed (${Ft}). This may indicate an invalid date or time range. Skipping custom tick interval.`);else switch(o){case"millisecond":u.ticks(ne.every(A));break;case"second":u.ticks(re.every(A));break;case"minute":u.ticks(ee.every(A));break;case"hour":u.ticks(te.every(A));break;case"day":u.ticks(Jt.every(A));break;case"week":u.ticks(de[q].every(A));break;case"month":u.ticks(Kt.every(A));break}}}if(R.append("g").attr("class","grid").attr("transform","translate("+f+", "+(v-50)+")").call(u).selectAll("text").style("text-anchor","middle").attr("fill","#000").attr("stroke","none").attr("font-size",10).attr("dy","1em"),r.db.topAxisEnabled()||i.topAxis){let A=er(y).tickSize(-v+b+i.gridLineStartPadding).tickFormat(Qt(m));if(s!==null){const o=parseInt(s[1],10);if(isNaN(o)||o<=0)ot.warn(`Invalid tick interval value: "${s[1]}". Skipping custom tick interval.`);else{const q=s[2],c=r.db.getWeekday()||i.weekday,F=y.domain(),L=F[0],V=F[1];if(z(L,V,o,q)<=Ft)switch(q){case"millisecond":A.ticks(ne.every(o));break;case"second":A.ticks(re.every(o));break;case"minute":A.ticks(ee.every(o));break;case"hour":A.ticks(te.every(o));break;case"day":A.ticks(Jt.every(o));break;case"week":A.ticks(de[c].every(o));break;case"month":A.ticks(Kt.every(o));break}}}R.append("g").attr("class","grid").attr("transform","translate("+f+", "+b+")").call(A).selectAll("text").style("text-anchor","middle").attr("fill","#000").attr("stroke","none").attr("font-size",10)}}l(Y,"makeGrid");function T(f,b){let x=0;const v=Object.keys(C).map(a=>[a,C[a]]);R.append("g").selectAll("text").data(v).enter().append(function(a){const d=a[0].split(Ie.lineBreakRegex),m=-(d.length-1)/2,u=_.createElementNS("http://www.w3.org/2000/svg","text");u.setAttribute("dy",m+"em");for(const[M,s]of d.entries()){const A=_.createElementNS("http://www.w3.org/2000/svg","tspan");A.setAttribute("alignment-baseline","central"),A.setAttribute("x","10"),M>0&&A.setAttribute("dy","1em"),A.textContent=s,u.appendChild(A)}return u}).attr("x",10).attr("y",function(a,d){if(d>0)for(let m=0;m<d;m++)return x+=v[d-1][1],a[1]*f/2+x*f+b;else return a[1]*f/2+b}).attr("font-size",i.sectionFontSize).attr("class",function(a){for(const[d,m]of S.entries())if(a[0]===m)return"sectionTitle sectionTitle"+d%i.numberSectionStyles;return"sectionTitle"})}l(T,"vertLabels");function h(f,b,x,v){const a=r.db.getTodayMarker();if(a==="off")return;const d=R.append("g").attr("class","today"),m=new Date,u=d.append("line");u.attr("x1",y(m)+f).attr("x2",y(m)+f).attr("y1",i.titleTopMargin).attr("y2",v-i.titleTopMargin).attr("class","today"),a!==""&&u.attr("style",a.replace(/,/g,";"))}l(h,"drawToday");function $(f){const b={},x=[];for(let v=0,a=f.length;v<a;++v)Object.prototype.hasOwnProperty.call(b,f[v])||(b[f[v]]=!0,x.push(f[v]));return x}l($,"checkUnique")},"draw"),on={setConf:nn,draw:an},cn=l(t=>`
  .mermaid-main-font {
        font-family: ${t.fontFamily};
  }

  .exclude-range {
    fill: ${t.excludeBkgColor};
  }

  .section {
    stroke: none;
    opacity: 0.2;
  }

  .section0 {
    fill: ${t.sectionBkgColor};
  }

  .section2 {
    fill: ${t.sectionBkgColor2};
  }

  .section1,
  .section3 {
    fill: ${t.altSectionBkgColor};
    opacity: 0.2;
  }

  .sectionTitle0 {
    fill: ${t.titleColor};
  }

  .sectionTitle1 {
    fill: ${t.titleColor};
  }

  .sectionTitle2 {
    fill: ${t.titleColor};
  }

  .sectionTitle3 {
    fill: ${t.titleColor};
  }

  .sectionTitle {
    text-anchor: start;
    font-family: ${t.fontFamily};
  }


  /* Grid and axis */

  .grid .tick {
    stroke: ${t.gridColor};
    opacity: 0.8;
    shape-rendering: crispEdges;
  }

  .grid .tick text {
    font-family: ${t.fontFamily};
    fill: ${t.textColor};
  }

  .grid path {
    stroke-width: 0;
  }


  /* Today line */

  .today {
    fill: none;
    stroke: ${t.todayLineColor};
    stroke-width: 2px;
  }


  /* Task styling */

  /* Default task */

  .task {
    stroke-width: 2;
  }

  .taskText {
    text-anchor: middle;
    font-family: ${t.fontFamily};
  }

  .taskTextOutsideRight {
    fill: ${t.taskTextDarkColor};
    text-anchor: start;
    font-family: ${t.fontFamily};
  }

  .taskTextOutsideLeft {
    fill: ${t.taskTextDarkColor};
    text-anchor: end;
  }


  /* Special case clickable */

  .task.clickable {
    cursor: pointer;
  }

  .taskText.clickable {
    cursor: pointer;
    fill: ${t.taskTextClickableColor} !important;
    font-weight: bold;
  }

  .taskTextOutsideLeft.clickable {
    cursor: pointer;
    fill: ${t.taskTextClickableColor} !important;
    font-weight: bold;
  }

  .taskTextOutsideRight.clickable {
    cursor: pointer;
    fill: ${t.taskTextClickableColor} !important;
    font-weight: bold;
  }


  /* Specific task settings for the sections*/

  .taskText0,
  .taskText1,
  .taskText2,
  .taskText3 {
    fill: ${t.taskTextColor};
  }

  .task0,
  .task1,
  .task2,
  .task3 {
    fill: ${t.taskBkgColor};
    stroke: ${t.taskBorderColor};
  }

  .taskTextOutside0,
  .taskTextOutside2
  {
    fill: ${t.taskTextOutsideColor};
  }

  .taskTextOutside1,
  .taskTextOutside3 {
    fill: ${t.taskTextOutsideColor};
  }


  /* Active task */

  .active0,
  .active1,
  .active2,
  .active3 {
    fill: ${t.activeTaskBkgColor};
    stroke: ${t.activeTaskBorderColor};
  }

  .activeText0,
  .activeText1,
  .activeText2,
  .activeText3 {
    fill: ${t.taskTextDarkColor} !important;
  }


  /* Completed task */

  .done0,
  .done1,
  .done2,
  .done3 {
    stroke: ${t.doneTaskBorderColor};
    fill: ${t.doneTaskBkgColor};
    stroke-width: 2;
  }

  .doneText0,
  .doneText1,
  .doneText2,
  .doneText3 {
    fill: ${t.taskTextDarkColor} !important;
  }

  /* Done task text displayed outside the bar sits against the diagram background,
     not against the done-task bar, so it must use the outside/contrast color. */
  .doneText0.taskTextOutsideLeft,
  .doneText0.taskTextOutsideRight,
  .doneText1.taskTextOutsideLeft,
  .doneText1.taskTextOutsideRight,
  .doneText2.taskTextOutsideLeft,
  .doneText2.taskTextOutsideRight,
  .doneText3.taskTextOutsideLeft,
  .doneText3.taskTextOutsideRight {
    fill: ${t.taskTextOutsideColor} !important;
  }


  /* Tasks on the critical line */

  .crit0,
  .crit1,
  .crit2,
  .crit3 {
    stroke: ${t.critBorderColor};
    fill: ${t.critBkgColor};
    stroke-width: 2;
  }

  .activeCrit0,
  .activeCrit1,
  .activeCrit2,
  .activeCrit3 {
    stroke: ${t.critBorderColor};
    fill: ${t.activeTaskBkgColor};
    stroke-width: 2;
  }

  .doneCrit0,
  .doneCrit1,
  .doneCrit2,
  .doneCrit3 {
    stroke: ${t.critBorderColor};
    fill: ${t.doneTaskBkgColor};
    stroke-width: 2;
    cursor: pointer;
    shape-rendering: crispEdges;
  }

  .milestone {
    transform: rotate(45deg) scale(0.8,0.8);
  }

  .milestoneText {
    font-style: italic;
  }
  .doneCritText0,
  .doneCritText1,
  .doneCritText2,
  .doneCritText3 {
    fill: ${t.taskTextDarkColor} !important;
  }

  /* Done-crit task text outside the bar — same reasoning as doneText above. */
  .doneCritText0.taskTextOutsideLeft,
  .doneCritText0.taskTextOutsideRight,
  .doneCritText1.taskTextOutsideLeft,
  .doneCritText1.taskTextOutsideRight,
  .doneCritText2.taskTextOutsideLeft,
  .doneCritText2.taskTextOutsideRight,
  .doneCritText3.taskTextOutsideLeft,
  .doneCritText3.taskTextOutsideRight {
    fill: ${t.taskTextOutsideColor} !important;
  }

  .vert {
    stroke: ${t.vertLineColor};
  }

  .vertText {
    font-size: 15px;
    text-anchor: middle;
    fill: ${t.vertLineColor} !important;
  }

  .activeCritText0,
  .activeCritText1,
  .activeCritText2,
  .activeCritText3 {
    fill: ${t.taskTextDarkColor} !important;
  }

  .titleText {
    text-anchor: middle;
    font-size: 18px;
    fill: ${t.titleColor||t.textColor};
    font-family: ${t.fontFamily};
  }
`,"getStyles"),ln=cn,gn={parser:vr,db:rn,renderer:on,styles:ln};export{gn as diagram};
