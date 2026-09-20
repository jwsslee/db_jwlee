"""Pastel edition — personal stock research dashboard. Read-only broker access."""
import hmac,json,re,hashlib
from datetime import timedelta
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from data import KIS,APIError,NAMES,now,number,krx_market,demo_history,demo_quote,demo_flow,demo_financials
from analytics import indicators,performance,align_prices,validate_notebook,evaluate_alert
from ui import style,hero,fmt,layout,plot,table,COLORS,UP,DOWN

st.set_page_config(page_title='이종완의 주식 분석 대시보드',page_icon='🌿',layout='wide')
style()
def secret(k,default=''):
    try:return st.secrets.get(k,default)
    except (FileNotFoundError,st.errors.StreamlitSecretNotFoundError):return default

@st.cache_resource(show_spinner=False)
def cached_client(key,password,env,class_identity,_cls):return _cls(key,password,env)
def client():return cached_client(KEY,SECRET,ENV,id(KIS),KIS)
@st.cache_data(ttl=90,show_spinner=False)
def cached_quote(key,password,env,kind,code,identity):
    return getattr(cached_client(key,password,env,identity[0],KIS),kind)(code),now()
@st.cache_data(ttl=1800,show_spinner=False)
def cached_research(key,password,env,kind,code,identity):
    return getattr(cached_client(key,password,env,identity[0],KIS),kind)(code),now()
@st.cache_data(ttl=3600,show_spinner=False)
def cached_market(key,market,day):return krx_market(key,market,day)

KEY=str(secret('KIS_APP_KEY')).strip();SECRET=str(secret('KIS_APP_SECRET')).strip();ENV=str(secret('KIS_ENV','prod')).strip()
if ENV not in ('prod','vps'):st.error('KIS_ENV는 prod 또는 vps여야 합니다.');st.stop()
PAGES=['마켓 라운지','종목 리서치','종목 비교','실적과 가치','조건 검색','내 포트폴리오','알림과 투자 노트','연결 안내']
with st.sidebar:
    st.markdown('## 이종완의\n주식 분석 대시보드')
    st.caption('P A S T E L   E D I T I O N  /  2.0')
    page=st.radio('리서치 메뉴',PAGES,label_visibility='collapsed')
    st.divider()
    mode=st.radio('데이터 모드',['데모','API 연결'],horizontal=True)
    watch_input=st.text_area('관심 종목 · 6자리 코드',value='005930,000660,035420,005380',height=90)
    entered=list(dict.fromkeys(x.strip() for x in watch_input.replace('\n',',').split(',') if x.strip()))
    codes=[c for c in entered if re.fullmatch(r'\d{6}',c)][:8]
    if len(codes)!=len(entered):st.caption('올바른 종목코드 최대 8개를 사용합니다.')
    if not codes:st.info('종목코드를 하나 이상 입력하세요.');st.stop()
    code=st.selectbox('분석 종목',codes,format_func=lambda c:f'{NAMES.get(c,c)} · {c}')
    if st.button('↻ 데이터 갱신',width='stretch'):
        cached_quote.clear();cached_research.clear();cached_market.clear()
        st.session_state.pop('account',None)
    st.caption('시세 90초 · 이력/재무 30분 캐시\n수동 갱신 · 한국시간(KST)')
    st.divider();st.caption('ROSE / 상승 · BLUE / 하락\n실제 키는 Streamlit Secrets에만 보관')
DEMO=mode=='데모'
hero(mode,page)
if DEMO:st.caption('◌ 데모 모드 · 모든 시세·실적·잔고는 가상 예시입니다. 실제 투자 정보가 아닙니다.')
if not DEMO and page!='연결 안내' and (not KEY or not SECRET):
    st.info('연결 안내 메뉴를 참고해 KIS_APP_KEY와 KIS_APP_SECRET을 설정하세요.');st.stop()
if not DEMO and ENV=='vps':st.info('모의 환경: 일부 시세·재무 API는 지원되지 않을 수 있습니다.')
render_cache={}

def fetch(kind,symbol):
    if (kind,symbol) in render_cache:return render_cache[(kind,symbol)]
    try:
        if DEMO:
            if kind=='quote':value=demo_quote(symbol)
            elif kind=='history':value=demo_history(symbol)
            elif kind=='flow':value=demo_flow(symbol)
            elif kind=='financials':value=demo_financials(symbol)
            elif kind=='benchmark':value=demo_history('100001' if symbol=='0001' else '100002')[['date','close']]
            else:value={'price':2748.32 if symbol=='0001' else 862.14,'change':.84 if symbol=='0001' else -.32}
            result=(value,now())
        else:
            func=cached_quote if kind in ('quote','index') else cached_research
            result=func(KEY,SECRET,ENV,kind,symbol,(id(KIS),id(APIError)))
    except (APIError,KeyError,ValueError,TypeError) as e:
        st.warning(str(e) if isinstance(e,APIError) else f'{symbol} · {kind}: 응답 형식이 예상과 다릅니다.')
        result=(None,None)
    render_cache[(kind,symbol)]=result
    return result

def price_cards():
    q,stamp=fetch('quote',code)
    for col,label,sym in zip(st.columns(4),['KOSPI','KOSDAQ',NAMES.get(code,code),'종목 거래대금'],['0001','1001',code,None]):
        if sym in ('0001','1001'):
            value,t=fetch('index',sym)
            col.metric(label,fmt(value['price'],2) if value else '—',fmt(value['change'],2,'%') if value else None,delta_color='inverse')
        elif sym:
            col.metric(label,fmt(q['price'],0,' 원') if q else '—',fmt(q['change'],2,'%') if q else None,delta_color='inverse')
        else:col.metric(label,fmt(q['value']/1e8,1,' 억') if q else '—')
    if stamp:st.caption(f'한국투자증권 · 조회 {stamp:%Y.%m.%d %H:%M:%S} KST · KRX 시세 / 마지막 체결 시각과 다를 수 있음')
    return q

def csv_download(df,name):
    st.download_button('CSV 내려받기',df.to_csv(index=False).encode('utf-8-sig'),file_name=name,mime='text/csv')

def market_data(market,day):
    if DEMO:
        rows=[]
        for c,n in NAMES.items():
            q=demo_quote(c);rows.append({'코드':c,'종목':n,'종가':q['price'],'등락률(%)':q['change'],'거래량':q['volume'],'거래대금':q['value']})
        return pd.DataFrame(rows)
    key=str(secret('KRX_API_KEY')).strip()
    if not key:st.info('시장 전체 조회에는 KRX_API_KEY가 필요합니다.');return None
    try:return cached_market(key,market,day.strftime('%Y%m%d'))
    except (APIError,KeyError,ValueError,TypeError) as e:
        st.warning(str(e) if isinstance(e,APIError) else 'KRX 데이터 형식을 확인하세요.');return None

def market_controls():
    a,b=st.columns([1,2]);market=a.selectbox('시장',['KOSPI','KOSDAQ'])
    d=now().date()-timedelta(days=1)
    while d.weekday()>4:d-=timedelta(days=1)
    day=b.date_input('KRX 기준일',value=d,max_value=now().date())
    st.caption('휴장일·미게시일은 이전 거래일을 선택하세요.' if not DEMO else '데모는 시장·날짜와 무관한 6개 가상 종목 예시입니다.')
    return market,day

if page=='마켓 라운지':
    price_cards()
    left,right=st.columns([1.65,1],gap='large')
    with left,st.container(border=True):
        st.subheader('관심 종목의 오늘')
        rows=[]
        for c in codes:
            q,_=fetch('quote',c)
            rows.append({'종목':NAMES.get(c,c),'코드':c,'현재가':q['price'] if q else np.nan,
                '등락률(%)':q['change'] if q else np.nan,'거래대금(억)':q['value']/1e8 if q else np.nan})
        table(pd.DataFrame(rows));st.caption('조회 시점 가격 · 거래대금은 당일 누적')
    with right,st.container(border=True):
        st.subheader('오늘의 리서치 루틴')
        st.markdown('**01** 시장의 방향과 거래대금 확인\n\n**02** 관심 종목의 가격·수급 비교\n\n**03** 실적과 투자 이유 점검')
        st.caption('왼쪽 메뉴에서 종목 비교와 투자 노트를 열어보세요.')
    st.subheader('시장 전체의 온도')
    market,day=market_controls();df=market_data(market,day)
    if df is not None:
        if df.empty:st.info('이 날짜의 시장 자료가 아직 없습니다.')
        else:
            changes=df['등락률(%)'];a,b,c=st.columns(3)
            a.metric('상승 / 하락',f'{(changes>0).sum():,} / {(changes<0).sum():,}')
            b.metric('거래대금 합계',fmt(df['거래대금'].sum(min_count=1)/1e12,2,' 조'))
            c.metric('상승 종목 비율',fmt((changes>0).sum()/changes.notna().sum()*100 if changes.notna().any() else np.nan,1,'%'))
            top=df.nlargest(15,'거래대금').copy()
            fig=go.Figure(go.Bar(x=top['거래대금']/1e8,y=top['종목'],orientation='h',marker_color=np.where(top['등락률(%)']>=0,'#dbaabc','#a8beda')))
            fig.update_layout(yaxis_autorange='reversed',xaxis_title='거래대금 · 억원')
            plot(fig,430);st.caption(f'KRX 일별매매정보 · {day:%Y.%m.%d} · 거래대금 상위 15종목')

elif page=='종목 리서치':
    q=price_cards();a,b,c=st.columns(3)
    days=a.selectbox('분석 기간',[30,90,180,365],index=2,format_func=lambda x:f'{x}일')
    candles=b.radio('차트 주기',['일봉','주봉'],horizontal=True)
    extra=c.selectbox('보조지표',['RSI','MACD','없음'])
    hist,stamp=fetch('history',code)
    if hist is not None and not hist.empty:
        d=indicators(hist);view=d[d.date>=pd.Timestamp(now().date()-timedelta(days=days))].copy()
        if view.empty:st.info('선택 기간 내 거래 데이터가 없습니다.')
        else:
            chart=view
            if candles=='주봉':
                chart=view.set_index('date').resample('W-FRI').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum',
                    'MA20':'last','MA60':'last','MA120':'last','upper':'last','lower':'last','RSI':'last','MACD':'last','Signal':'last'}).dropna(subset=['close']).reset_index()
            with st.container(border=True):
                st.subheader(f'{NAMES.get(code,code)} · 가격의 흐름')
                fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.04,row_heights=[.77,.23])
                fig.add_trace(go.Candlestick(x=chart.date,open=chart.open,high=chart.high,low=chart.low,close=chart.close,
                    name='수정주가',increasing_line_color=UP,decreasing_line_color=DOWN),row=1,col=1)
                for n,color in [(20,COLORS[0]),(60,COLORS[1]),(120,COLORS[4])]:
                    fig.add_trace(go.Scatter(x=chart.date,y=chart[f'MA{n}'],name=f'{n}일 평균',line=dict(color=color,width=1.5)),row=1,col=1)
                fig.add_trace(go.Bar(x=chart.date,y=chart.volume,name='거래량',showlegend=False,marker_color=np.where(chart.close>=chart.open,'#dbaabc','#afc4df')),row=2,col=1)
                fig.update_layout(xaxis_rangeslider_visible=False);fig.update_yaxes(title_text='원',row=1,col=1);fig.update_yaxes(title_text='주',row=2,col=1)
                plot(fig,480);st.caption(f'수정주가 · 실제 표시 {view.date.min():%Y.%m.%d}–{view.date.max():%Y.%m.%d} · 주봉의 이동평균도 일 단위 기준 / 마지막 주는 미완료 가능')
            metrics=performance(view.close)
            for col,(label,value) in zip(st.columns(3),metrics.items()):col.metric(label,fmt(value,2,'%'))
            if extra!='없음':
                fig=go.Figure()
                if extra=='RSI':
                    fig.add_trace(go.Scatter(x=view.date,y=view.RSI,name='RSI 14',line_color=COLORS[0]));fig.add_hrect(y0=30,y1=70,fillcolor='#e9e3f4',opacity=.4,line_width=0);fig.update_yaxes(range=[0,100])
                else:
                    for col in ['MACD','Signal']:fig.add_trace(go.Scatter(x=view.date,y=view[col],name=col))
                plot(fig,230);st.caption('보조지표는 참고 정보이며 자동 매매 신호가 아닙니다.')
            with st.expander('가격 원자료 / 다운로드'):table(view[['date','open','high','low','close','volume']]);csv_download(view,'price_history.csv')
    with st.container(border=True):
        st.subheader('투자자 수급')
        flow,stamp=fetch('flow',code)
        if flow is not None and not flow.empty:
            count=st.radio('누적 기간',[5,20],horizontal=True,format_func=lambda x:f'{x}거래일');d=flow.tail(count)
            for col,name in zip(st.columns(3),['외국인','기관','개인']):col.metric(name,fmt(d[name].sum(min_count=1),0,' 주'))
            fig=go.Figure()
            for name in ['외국인','기관','개인']:fig.add_trace(go.Bar(x=d.date,y=d[name],name=name))
            fig.update_layout(barmode='group');plot(fig,280)
            st.caption(f'한국투자증권 · 순매수 수량 · 장 종료 후 제공 · 최근 {flow.date.max():%Y.%m.%d} · 실제 {len(d)}개 날짜 누적 / 수정 가능')

elif page=='종목 비교':
    st.subheader('같은 출발점에서 비교하기')
    selected=st.multiselect('비교 종목 · 최대 5개',codes,default=codes[:3],format_func=lambda x:NAMES.get(x,x),max_selections=5)
    a,b=st.columns(2);days=a.selectbox('비교 기간',[30,90,180,365],index=2)
    bm=b.selectbox('비교 지수',['KOSPI','KOSDAQ'])
    frames={}
    with st.spinner('공통 거래일과 가격 이력을 맞추는 중입니다…'):
        for c in selected:
            d,_=fetch('history',c)
            if d is not None:frames[f'{NAMES.get(c,c)} ({c})']=d
        d,_=fetch('benchmark','0001' if bm=='KOSPI' else '1001')
        if d is not None:frames[bm]=d
    aligned=align_prices(frames,now().date()-timedelta(days=days),now().date())
    if len(aligned)<2:st.info('비교하려면 공통 거래일의 데이터가 2개 이상 필요합니다.')
    else:
        norm=aligned/aligned.iloc[0]*100;fig=go.Figure()
        for col in norm:fig.add_trace(go.Scatter(x=norm.index,y=norm[col],name=col,line=dict(width=2.5,dash='dot' if col==bm else 'solid')))
        plot(fig,420);st.caption(f'공통 시작일=100 · {aligned.index.min():%Y.%m.%d}–{aligned.index.max():%Y.%m.%d} · 배당 미포함 가격수익률')
        rows=[];base=performance(aligned[bm])['수익률(%)'] if bm in aligned else np.nan
        for col in aligned:
            r=performance(aligned[col]);r['지수 대비(%p)']=r['수익률(%)']-base;rows.append({'종목':col,**r})
        table(pd.DataFrame(rows).round(2));csv_download(pd.DataFrame(rows),'comparison.csv')
        if len(aligned.columns)>1:
            with st.expander('일별 수익률 상관관계'):
                corr=aligned.pct_change(fill_method=None).dropna().corr()
                fig=go.Figure(go.Heatmap(z=corr.values,x=corr.columns,y=corr.index,zmin=-1,zmax=1,colorscale=[[0,'#b4cce6'],[.5,'#f8f4f8'],[1,'#b7a3d3']],text=corr.round(2).values,texttemplate='%{text}'))
                plot(fig,340)

elif page=='실적과 가치':
    q,stamp=fetch('quote',code)
    st.subheader(f'{NAMES.get(code,code)} · 가격과 기업 가치')
    if q:
        for col,label,field,suffix in zip(st.columns(4),['PER','PBR','EPS','시가총액'],['per','pbr','eps','market_cap'],[' 배',' 배',' 원',' 억']):
            value=q.get(field,np.nan)
            if field in ('per','pbr') and (pd.isna(value) or value<=0):value=np.nan
            col.metric(label,fmt(value,2 if field in ('per','pbr') else 0,suffix))
        st.caption('한국투자증권 시세 응답 기준 · PER/PBR 0 이하 또는 미제공 값은 — 표시 · 산정 기준은 재무표 결산 시점과 다를 수 있음')
    info,stamp=fetch('financials',code)
    if info is not None:
        ratios=info['financial-ratio'];income=info['income-statement']
        if ratios.empty and income.empty:st.info('제공되는 연간 재무자료가 없습니다.')
        if not ratios.empty:
            latest=ratios.iloc[-1];st.caption(f'연간 재무비율 · 결산 {latest.period[:4]}.{latest.period[4:]} · 조회 {stamp:%Y.%m.%d %H:%M}')
            for col,label,field in zip(st.columns(4),['매출 증가율','영업이익 증가율','ROE','부채비율'],['revenue_growth','operating_growth','roe','debt_ratio']):col.metric(label,fmt(latest[field],1,'%'))
            fig=go.Figure()
            for field,label in [('roe','ROE'),('revenue_growth','매출 증가율')]:fig.add_trace(go.Scatter(x=ratios.period,y=ratios[field],name=label,mode='lines+markers'))
            plot(fig,300)
        if not income.empty:
            a,b=st.columns(2)
            with a,st.container(border=True):
                st.subheader('매출 규모의 변화')
                usable=income[income.revenue>0]
                if not usable.empty:
                    fig=go.Figure(go.Bar(x=usable.period,y=usable.revenue/usable.revenue.iloc[0]*100,marker_color='#b7acd2',name='매출 지수'))
                    plot(fig,280);st.caption(f'결산 {usable.period.iloc[0]}의 매출=100 · 연간 기준')
                else:st.info('매출 자료가 부족합니다.')
            with b,st.container(border=True):
                st.subheader('영업이익률')
                margin=income.operating/income.revenue.where(income.revenue>0)*100
                plot(go.Figure(go.Bar(x=income.period,y=margin,marker_color='#9ec8bb',name='영업이익률(%)')),280)
                st.caption('연간 영업이익 ÷ 연간 매출 × 100')
        st.info('증가율은 전기 적자·흑자 전환 등으로 해석이 달라질 수 있습니다. 재무자료는 결산 이후 공시·정정에 따라 변경됩니다.')
        st.markdown('[DART 공시 검색](https://dart.fss.or.kr/dsab001/main.do) · [KRX KIND 공시](https://kind.krx.co.kr/)')
        st.caption('공시 전문과 배당·실적 발표 일정은 위 공식 사이트에서 확인하세요. 이 앱은 공시 일정 자동 수집을 제공하지 않습니다.')

elif page=='조건 검색':
    st.subheader('나의 기준으로 시장 좁히기')
    market,day=market_controls();df=market_data(market,day)
    a,b,c=st.columns(3)
    min_value=a.number_input('최소 거래대금 · 억원',min_value=0.,value=100.,step=50.)
    change=b.slider('등락률 범위 · %',-30.,30.,(-5.,15.))
    keyword=c.text_input('종목명 또는 코드')
    if df is not None:
        if df.empty:st.info('선택 날짜의 데이터가 없습니다.')
        else:
            mask=(df['거래대금']>=min_value*1e8)&df['등락률(%)'].between(*change)
            if keyword:mask &= df['종목'].str.contains(keyword,regex=False,na=False)|df['코드'].str.contains(keyword,regex=False,na=False)
            found=df[mask].sort_values('거래대금',ascending=False).copy();found['거래대금(억)']=found.pop('거래대금')/1e8
            st.caption(f'{len(df):,}종목 중 {len(found):,}종목 · {day:%Y.%m.%d} KRX 일별자료 · 결측값은 조건 통과에서 제외')
            table(found);csv_download(found,'screening.csv')
    st.divider();st.subheader('관심 종목 가치 필터')
    per_limit=st.slider('양수 PER 상한 · 배',1,100,25)
    if st.button('관심 종목 PER 조회'):
        rows=[]
        for c in codes:
            q,_=fetch('quote',c)
            if q and 0<q.get('per',np.nan)<=per_limit:rows.append({'종목':NAMES.get(c,c),'코드':c,'PER':q['per'],'PBR':q['pbr']})
        if rows:table(pd.DataFrame(rows))
        else:st.info('조건을 충족한 종목이 없거나 조회 데이터가 없습니다.')
    st.caption('시장 전체 필터는 KRX 일별 데이터, 가치 필터는 관심 종목의 현재 조회 데이터 기준입니다.')

elif page=='내 포트폴리오':
    st.subheader('수익과 위험을 함께 살피기')
    gate=str(secret('DASHBOARD_PASSWORD'));unlocked=DEMO
    if not DEMO:
        if not gate:st.info('Secrets에 DASHBOARD_PASSWORD를 설정하세요.')
        else:
            supplied=st.text_input('잔고 조회 비밀번호',type='password',key='account_password')
            unlocked=hmac.compare_digest(supplied.encode(),gate.encode())
            if supplied and not unlocked:st.warning('비밀번호가 일치하지 않습니다.')
    if unlocked:
        result=None
        if DEMO:
            h=pd.DataFrame({'종목':['삼성전자','SK하이닉스','NAVER'],'코드':['005930','000660','035420'],'수량':[100,20,10],
                '평균매입가':[70000,170000,200000],'현재가':[74500,182000,193000],'평가금액':[7450000,3640000,1930000],
                '평가손익':[450000,240000,-70000],'수익률(%)':[6.43,7.06,-3.5]})
            result=(h,{'tot_evlu_amt':'18020000','dnca_tot_amt':'5000000','evlu_pfls_smtl_amt':'620000'},now())
        else:
            cano=str(secret('KIS_CANO'));product=str(secret('KIS_ACNT_PRDT_CD','01'))
            account_id=hashlib.sha256((KEY+ENV+cano+product).encode()).hexdigest()
            if st.session_state.get('account_id')!=account_id:st.session_state.pop('account',None)
            st.session_state.account_id=account_id
            if not re.fullmatch(r'\d{8}',cano) or not re.fullmatch(r'\d{2}',product):st.info('계좌 앞 8자리와 상품코드 2자리를 확인하세요.')
            elif st.button('잔고 조회 / 갱신',type='primary'):
                try:st.session_state.account=client().balance(cano,product)
                except (APIError,KeyError,ValueError,TypeError) as e:
                    st.session_state.pop('account',None);st.warning(str(e) if isinstance(e,APIError) else '잔고 데이터 형식을 확인하세요.')
            result=st.session_state.get('account')
        if result:
            h,summary,stamp=result
            for col,label,field in zip(st.columns(3),['총 평가금액','주식 평가손익','예수금'],['tot_evlu_amt','evlu_pfls_smtl_amt','dnca_tot_amt']):col.metric(label,fmt(number(summary.get(field)),0,' 원'))
            st.caption(f'조회 {stamp:%Y.%m.%d %H:%M:%S} KST · 예수금은 주문가능금액과 다릅니다.')
            if h.empty:st.info('보유 중인 국내주식이 없습니다.')
            else:
                a,b=st.columns([1.7,1]);total=h['평가금액'].sum(min_count=1)
                with a:table(h);csv_download(h,'holdings.csv')
                with b:
                    positive=h[h['평가금액']>0]
                    plot(go.Figure(go.Pie(labels=positive['종목'],values=positive['평가금액'],hole=.75,marker_colors=COLORS,textinfo='percent')),300)
                    st.caption('국내주식 평가금액 비중 · 현금 제외')
                if total>0:
                    a,b,c=st.columns(3);weights=h['평가금액']/total*100
                    a.metric('최대 종목 비중',fmt(weights.max(),1,'%'));b.metric('상위 3종목 비중',fmt(weights.nlargest(3).sum(),1,'%'));c.metric('보유 종목',f'{len(h)}개')
                    limit=st.slider('한 종목 비중 점검 기준 · %',10,100,40)
                    if weights.max()>limit:st.warning(f'가장 큰 보유 종목이 설정 기준 {limit}%를 넘습니다.')
                    else:st.success('현재 한 종목 비중이 설정한 기준 이내입니다.')
                st.caption('누적 계좌 수익률은 입출금·매매·배당 이력이 필요해 계산하지 않습니다. 현재 보유 주식의 평가손익을 표시합니다.')
        if not DEMO and st.button('잔고 숨기기'):
            st.session_state.pop('account',None);st.session_state.pop('account_password',None);st.rerun()
    else:st.session_state.pop('account',None)

elif page=='알림과 투자 노트':
    st.subheader('내가 정한 기준에 도달했나요?')
    st.caption('앱에서 조회할 때만 조건을 점검합니다. 앱을 닫은 동안의 감시나 이메일·문자 발송은 없습니다.')
    a,b,c=st.columns(3)
    field=a.selectbox('점검 지표',['현재가','등락률(%)','거래대금(억원)']);op=b.selectbox('조건',['이상','이하'])
    threshold=c.number_input('기준값',value=80000. if field=='현재가' else 3.,step=1.)
    q,stamp=fetch('quote',code)
    value=({'현재가':q['price'],'등락률(%)':q['change'],'거래대금(억원)':q['value']/1e8}[field]) if q else np.nan
    status=evaluate_alert(value,op,threshold)
    st.metric(f'{NAMES.get(code,code)} · {field}',fmt(value,2))
    if status=='조건 충족':st.success(f'조건 충족 · {field} {threshold:,.2f} {op}')
    elif status=='대기':st.info('아직 설정 조건에 도달하지 않았습니다.')
    else:st.info('데이터가 없어 조건을 판단할 수 없습니다.')
    st.divider();st.subheader('투자 이유를 기록하는 공간')
    st.caption('메모는 현재 세션에 저장됩니다. 세션 종료 전에 JSON으로 내려받으면 다음 접속에서 복원할 수 있습니다.')
    st.session_state.setdefault('notes',[])
    with st.form('note_form',clear_on_submit=True):
        reason=st.text_area('투자 이유',max_chars=5000);condition=st.text_input('다음 점검에서 확인할 조건',max_chars=5000)
        due=st.date_input('다음 점검일',value=now().date()+timedelta(days=30))
        submit=st.form_submit_button('노트 추가')
    if submit:
        if not reason.strip():st.warning('투자 이유를 입력하세요.')
        elif len(st.session_state.notes)>=1000:st.warning('최대 1,000개까지 저장할 수 있습니다.')
        else:st.session_state.notes.append({'날짜':str(now().date()),'종목':f'{NAMES.get(code,code)} ({code})','매수 이유':reason,'점검 조건':condition,'다음 점검일':str(due)})
    if st.session_state.notes:
        notes=pd.DataFrame(st.session_state.notes);table(notes)
        overdue=pd.to_datetime(notes['다음 점검일'],errors='coerce').dt.date.apply(lambda d:False if pd.isna(d) else d<=now().date()).sum()
        if overdue:st.info(f'점검 예정일이 오늘이거나 지난 노트가 {overdue}개 있습니다.')
        st.download_button('투자 노트 JSON 저장',json.dumps({'version':1,'notes':st.session_state.notes},ensure_ascii=False,indent=2),file_name='investment_notes.json',mime='application/json')
        selected_note=st.selectbox('삭제할 노트',range(len(notes)),format_func=lambda i:f"{i+1}. {notes.iloc[i]['종목']} · {notes.iloc[i]['날짜']}")
        if st.button('선택한 노트 삭제'):st.session_state.notes.pop(selected_note);st.rerun()
    with st.expander('저장한 노트 불러오기'):
        uploaded=st.file_uploader('investment_notes.json',type=['json'])
        st.caption('불러오면 현재 노트를 파일 내용으로 교체합니다.')
        if uploaded and st.button('파일에서 복원'):
            try:
                if uploaded.size>5_000_000:raise ValueError('5MB 이하 파일만 사용할 수 있습니다.')
                st.session_state.notes=validate_notebook(json.loads(uploaded.getvalue()));st.rerun()
            except (ValueError,TypeError,UnicodeError):st.error('유효한 투자 노트 JSON 파일인지 확인하세요.')

elif page=='연결 안내':
    st.subheader('나의 데이터 연결')
    st.code('''KRX_API_KEY = "KRX 인증키"
KIS_APP_KEY = "한국투자증권 App Key"
KIS_APP_SECRET = "한국투자증권 App Secret"
KIS_ENV = "prod"
KIS_CANO = "계좌 앞 8자리"
KIS_ACNT_PRDT_CD = "01"
DASHBOARD_PASSWORD = "나만의 잔고조회 비밀번호"''',language='toml')
    st.write('새 Streamlit 앱의 Secrets에 설정하세요. 기존 앱의 Secrets는 새 앱으로 자동 복사되지 않습니다.')
    st.write('실전은 prod, 모의는 vps입니다. 계좌 정보는 잔고 조회에만 사용됩니다.')
    st.write('KRX는 유가증권·코스닥 일별매매정보 이용 승인이 필요합니다. 가격·재무·지수는 한국투자증권 API를 사용합니다.')
    st.write('조회 오류에는 오류 코드와 조회 종류가 표시됩니다. 업데이트 후 이전 오류가 남으면 앱을 Reboot 하세요.')
    st.markdown('[KIS Developers](https://apiportal.koreainvestment.com/) · [KRX OpenAPI](https://openapi.krx.co.kr/)')
    st.info('개인 계좌를 연결한 앱은 비공개로 운영하세요. 잔고 비밀번호는 간단한 추가 잠금이며 사용자별 로그인 기능이 아닙니다.')
st.markdown('<div class="footer">JONG WAN LEE · PASTEL EDITION &nbsp; / &nbsp; KRX · KIS &nbsp; / &nbsp; KST &nbsp; / &nbsp; 조회 전용</div>',unsafe_allow_html=True)
