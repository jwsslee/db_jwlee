import html
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

COLORS=['#7c77b7','#5f9e96','#cc879c','#86a2ce','#c2a26e','#a28bad']
UP='#b36783';DOWN='#6588b5';TEXT='#505b77'

def style():
    st.markdown('''<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&family=Noto+Serif+KR:wght@500;600&display=swap');
html,body,[data-testid="stApp"]{font-family:'Noto Sans KR',sans-serif;color:#505b77;}
.stApp{background:linear-gradient(130deg,#f4f1f8 0%,#f8f6f2 53%,#edf6f4 100%);color:#505b77;}
.block-container{padding-top:2.1rem;padding-bottom:3rem;max-width:1500px;}
[data-testid="stHeader"]{background:rgba(248,246,251,.85);}
[data-testid="stSidebar"]{background:#ece8f4;border-right:1px solid #ded8eb;}
[data-testid="stSidebar"] h2{font-family:'Noto Serif KR',serif;color:#665b89;font-size:1.3rem;line-height:1.6;}
h1,h2,h3{color:#615779!important;letter-spacing:-.7px;}
h1{font-family:'Noto Serif KR',serif!important;font-size:2.15rem!important;font-weight:600!important;line-height:1.5!important;}
h3{font-size:1.08rem!important;}
[data-testid="stMetric"]{background:rgba(255,255,255,.8);border:1px solid #e5e0ee;border-radius:18px;padding:20px 22px;box-shadow:0 8px 26px #7f719208;}
[data-testid="stMetricLabel"]{color:#77718a;font-size:.82rem;}
[data-testid="stMetricValue"]{color:#655d84;font-size:1.85rem;letter-spacing:-.8px;}
[data-testid="stVerticalBlockBorderWrapper"]>div{border-radius:20px;border-color:#e3dfeb!important;background:#ffffff70;}
[data-testid="stCaptionContainer"]{color:#788298;}
.stButton>button,.stDownloadButton>button{border-radius:12px;border-color:#d9d1e7;color:#665a88;}
.stButton>button[kind="primary"]{background:#8577ad;border-color:#8577ad;color:#fff;}
[data-baseweb="input"],[data-baseweb="select"]>div,[data-baseweb="textarea"]{border-radius:12px!important;}
.hero{border:1px solid #e4ddee;border-radius:24px;background:linear-gradient(110deg,#eee8f6,#f8eee9 62%,#e6f2ee);padding:30px 32px;margin-bottom:24px;position:relative;overflow:hidden;}
.hero:after{content:'◌';position:absolute;right:35px;top:-24px;font-size:185px;line-height:1;color:#c4b9db66;pointer-events:none;}
.hero .kicker{font-size:10px;letter-spacing:3px;color:#827397;font-weight:700;}
.hero h1{margin:8px 0 4px;padding:0;}
.hero p{color:#7a748b;font-size:13px;margin:6px 0 0;}
.pill{display:inline-block;padding:5px 11px;border-radius:20px;background:#fff9;color:#7c6c91;font-size:11px;margin-bottom:12px;}
.page-label{font-size:11px;letter-spacing:2px;color:#8b7a9f;margin:18px 0 7px;}
.footer{border-top:1px solid #e1dce9;margin-top:30px;padding-top:16px;color:#898399;font-size:11px;letter-spacing:.5px;}
@media(max-width:700px){.block-container{padding:1rem;}.hero{padding:20px;}.hero h1{font-size:1.55rem!important;}.hero:after{display:none;}}
</style>''',unsafe_allow_html=True)

def hero(mode,page):
    st.markdown(f'''<div class="hero"><div class="kicker">JONG WAN LEE · PRIVATE RESEARCH DESK</div>
<div class="pill">{'DEMO / 가상 데이터' if mode=='데모' else 'KRX + KIS / 조회 전용'}</div>
<h1>이종완의 주식 분석 대시보드</h1><p>차분하게 시장을 읽고, 근거 있는 투자 기록을 쌓아갑니다. &nbsp; / &nbsp; {html.escape(page)}</p></div>''',unsafe_allow_html=True)

def fmt(value,decimals=0,suffix=''):
    return '—' if value is None or pd.isna(value) else f'{value:,.{decimals}f}{suffix}'

def layout(fig,height=360):
    fig.update_layout(template='plotly_white',height=height,paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
        colorway=COLORS,font=dict(family='Noto Sans KR, sans-serif',size=12,color=TEXT),
        margin=dict(l=15,r=15,t=35,b=15),legend=dict(orientation='h',y=1.12,x=0),hovermode='x unified')
    fig.update_xaxes(showgrid=False,zeroline=False)
    fig.update_yaxes(gridcolor='#e7e3ee',zerolinecolor='#ddd7e6')
    return fig

def plot(fig,height=360,key=None):
    st.plotly_chart(layout(fig,height),width='stretch',key=key,config={'displaylogo':False})

def table(frame):
    st.dataframe(frame,hide_index=True,width='stretch',column_config={
        c:st.column_config.NumberColumn(format='localized') for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])})
