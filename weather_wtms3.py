import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import datetime
from datetime import date, timedelta, datetime as dt
import json
import io
import requests
import re
from io import StringIO, BytesIO
import streamlit as st
import openpyxl

# 페이지 설정
st.set_page_config(
    page_title="하수처리장 측정데이터 + 기상데이터 통합 분석 시스템",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 기상청 API 설정
KMA_API_BASE_URL = "https://apihub.kma.go.kr/api/typ01/url/kma_sfctm3.php"
DEFAULT_API_KEY = "86OQsBWCRC-jkLAVgtQvUw"

# 기상관측소 정보 (광주 지역 중심으로 확장)
WEATHER_STATIONS = {
    140: {"name": "군산", "lat": 36.0053, "lon": 126.76135, "region": "전라북도"},
    146: {"name": "전주", "lat": 35.84092, "lon": 127.11718, "region": "전라북도"},
    156: {"name": "광주", "lat": 35.17294, "lon": 126.89156, "region": "광주광역시"},
    165: {"name": "목포", "lat": 34.81732, "lon": 126.38151, "region": "전라남도"},
    168: {"name": "여수", "lat": 34.73929, "lon": 127.74063, "region": "전라남도"},
    170: {"name": "완도", "lat": 34.73929, "lon": 127.74063, "region": "전라남도"},
    172: {"name": "고창", "lat": 34.73929, "lon": 127.74063, "region": "전라북도"},
    174: {"name": "순천", "lat": 34.73929, "lon": 127.74063, "region": "전라남도"},
    184: {"name": "제주", "lat": 33.51411, "lon": 126.52969, "region": "제주특별자치도"},
    185: {"name": "서귀포고산", "lat": 33.29382, "lon": 126.16283, "region": "제주특별자치도"},
    188: {"name": "서귀포성산", "lat": 33.38677, "lon": 126.8802, "region": "제주특별자치도"},
    189: {"name": "서귀포", "lat": 33.24616, "lon": 126.5653, "region": "제주특별자치도"},
    247: {"name": "남원", "lat": 33.24616, "lon": 126.5653, "region": "전라북도"},
    248: {"name": "장수", "lat": 33.24616, "lon": 126.5653, "region": "전라북도"}
}


# 기상 요소 정보 (하수처리장 분석용으로 선별)
# WEATHER_ELEMENTS = {
#     "TA": {"name": "기온", "unit": "°C", "color": "#FF6B6B"},
#     "HM": {"name": "상대습도", "unit": "%", "color": "#45B7D1"},
#     "RN": {"name": "강수량", "unit": "mm", "color": "#96CEB4"},
#     "SS": {"name": "일조시간", "unit": "hr", "color": "#F39C12"},
#     "SI": {"name": "일사량", "unit": "MJ/m²", "color": "#F7DC6F"}
# }

WEATHER_ELEMENTS = {
    "기온": {"name": "기온", "unit": "°C", "color": "#FF6B6B"},
    "상대습도": {"name": "상대습도", "unit": "%", "color": "#45B7D1"},
    "강수량": {"name": "강수량", "unit": "mm", "color": "#96CEB4"},
    "일조시간": {"name": "일조시간", "unit": "hr", "color": "#F39C12"},
    "일사량": {"name": "일사량", "unit": "MJ/m²", "color": "#F7DC6F"}
}


# 하수처리장 측정 항목 정보
SEWAGE_PARAMETERS = {
    "TOC": {"name": "총유기탄소", "unit": "mg/L", "color": "#8E44AD"},
    "SS": {"name": "부유물질", "unit": "mg/L", "color": "#2ECC71"},
    "T-N": {"name": "총질소", "unit": "mg/L", "color": "#E74C3C"},
    "T-P": {"name": "총인", "unit": "mg/L", "color": "#F39C12"},
    "pH": {"name": "수소이온농도", "unit": "-", "color": "#9B59B6"},
    "적산유량": {"name": "적산유량", "unit": "㎥/hr", "color": "#1ABC9C"}
}

def parse_excel_file(uploaded_file):
    """
    업로드된 엑셀 파일을 파싱하여 DataFrame으로 변환
    """
    try:
        # 엑셀 파일 읽기
        df = pd.read_excel(uploaded_file, header=None)
        
        # 첫 번째 행에서 제목 정보 추출
        title_info = df.iloc[0, 0] if not pd.isna(df.iloc[0, 0]) else "하수처리장 측정데이터"
        
        # 헤더 정보 파싱 (1행과 2행)
        header1 = df.iloc[1].fillna('')
        header2 = df.iloc[2].fillna('')
        
        # 실제 데이터는 3행부터
        data_rows = df.iloc[3:].reset_index(drop=True)
        
        # 컬럼 매핑 생성 - 개선된 로직
        column_mapping = {}
        parameter_columns = {}
        current_param = None
        
        for i, (h1, h2) in enumerate(zip(header1, header2)):
            if i == 0:  # 방류구
                column_mapping[i] = '방류구'
            elif i == 1:  # 측정일자
                column_mapping[i] = 'date'
            elif i == 2:  # 측정시간
                column_mapping[i] = 'time'
            else:
                # 주 헤더가 있으면 새로운 파라미터 시작
                if h1 and str(h1).strip():
                    # 파라미터명에서 단위 제거
                    if '(' in str(h1):
                        current_param = str(h1).split('(')[0].strip()
                    else:
                        current_param = str(h1).strip()
                    
                    if current_param not in parameter_columns:
                        parameter_columns[current_param] = {}
                
                # 부 헤더로 컬럼 타입 결정
                if current_param and str(h2).strip():
                    h2_clean = str(h2).strip()
                    
                    if h2_clean == '기준치':
                        parameter_columns[current_param]['standard'] = i
                        column_mapping[i] = f'{current_param}_기준치'
                    elif h2_clean == '측정치':
                        parameter_columns[current_param]['value'] = i
                        column_mapping[i] = f'{current_param}_측정치'
                    elif h2_clean == '상태정보':
                        parameter_columns[current_param]['status'] = i
                        column_mapping[i] = f'{current_param}_상태정보'
                    elif h2_clean == '대체값':
                        parameter_columns[current_param]['replacement'] = i
                        column_mapping[i] = f'{current_param}_대체값'
                    elif h2_clean == '대체코드':
                        parameter_columns[current_param]['replacement_code'] = i
                        column_mapping[i] = f'{current_param}_대체코드'
        
        # DataFrame 생성
        processed_data = []
        
        for _, row in data_rows.iterrows():
            if pd.isna(row.iloc[1]) or pd.isna(row.iloc[2]):  # 날짜나 시간이 없으면 건너뛰기
                continue
                
            record = {
                '방류구': row.iloc[0],
                'date': row.iloc[1],
                'time': str(row.iloc[2]).replace('시', ''),
                'datetime_str': f"{row.iloc[1]} {str(row.iloc[2]).replace('시', '')}:00"
            }
            
            # 측정항목별 데이터 추가
            for param, cols in parameter_columns.items():
                if 'standard' in cols:
                    record[f'{param}_기준치'] = row.iloc[cols['standard']] if not pd.isna(row.iloc[cols['standard']]) else None
                if 'value' in cols:
                    record[f'{param}_측정치'] = row.iloc[cols['value']] if not pd.isna(row.iloc[cols['value']]) else None
                if 'status' in cols:
                    record[f'{param}_상태정보'] = row.iloc[cols['status']] if not pd.isna(row.iloc[cols['status']]) else None
                if 'replacement' in cols:
                    record[f'{param}_대체값'] = row.iloc[cols['replacement']] if not pd.isna(row.iloc[cols['replacement']]) else None
                if 'replacement_code' in cols:
                    record[f'{param}_대체코드'] = row.iloc[cols['replacement_code']] if not pd.isna(row.iloc[cols['replacement_code']]) else None
            
            processed_data.append(record)
        
        result_df = pd.DataFrame(processed_data)
        
        # datetime 컬럼 생성
        result_df['datetime'] = pd.to_datetime(result_df['datetime_str'], errors='coerce')
        result_df = result_df.dropna(subset=['datetime'])
        
        # 시간별로 정렬
        result_df = result_df.sort_values('datetime').reset_index(drop=True)
        
        return result_df, title_info, list(parameter_columns.keys())
        
    except Exception as e:
        raise Exception(f"엑셀 파일 파싱 오류: {str(e)}")

def fetch_kma_data_simple(station_id, start_date, end_date, api_key=DEFAULT_API_KEY):
    """
    기상청 API에서 기상 데이터를 가져오는 간소화된 함수
    """
    try:
        # API 요청을 위한 시간 포맷 변환
        start_datetime = dt.combine(start_date, dt.min.time())
        end_datetime = dt.combine(end_date, dt.max.time().replace(microsecond=0))
        
        # 기상청 API 시간 포맷: YYYYMMDDHHMM
        tm1 = start_datetime.strftime('%Y%m%d%H%M')
        tm2 = end_datetime.strftime('%Y%m%d%H%M')
        
        # API 요청 URL 구성
        params = {
            'tm1': tm1,
            'tm2': tm2,
            'stn': station_id,
            'help': 0,
            'authKey': api_key
        }
        
        # SSL 검증 무시 옵션으로 요청
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        response = requests.get(KMA_API_BASE_URL, params=params, timeout=30, verify=False)
        response.raise_for_status()
        
        # 응답 데이터 파싱
        content = response.text
        
        if not content or len(content) < 100:
            raise ValueError("API 응답이 비어있거나 너무 짧습니다.")
        
        # #START7777과 #7777END 사이의 데이터 추출
        start_marker = "#START7777"
        end_marker = "#7777END"
        
        start_idx = content.find(start_marker)
        end_idx = content.find(end_marker)
        
        if start_idx == -1 or end_idx == -1:
            raise ValueError("API 응답에서 데이터 마커를 찾을 수 없습니다.")
        
        # 실제 데이터 부분 추출
        data_content = content[start_idx + len(start_marker):end_idx].strip()
        
        # 주석 라인들 제거
        lines = data_content.split('\n')
        data_lines = []
        
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#') and not line.startswith('-') and len(line) > 10:
                if re.match(r'^\d{10}', line):
                    data_lines.append(line)
        
        if not data_lines:
            raise ValueError("파싱할 수 있는 데이터가 없습니다.")
        
        # 데이터 파싱
        parsed_data = []
        
        for line in data_lines:
            fields = line.split()
            
            if len(fields) < 12:
                continue
            
            try:
                # 시간 정보 파싱 (YYYYMMDDHHMM 형식)
                datetime_str = fields[0]
                parsed_datetime = dt.strptime(datetime_str, '%Y%m%d%H%M')
                
                # 각 필드 파싱 (-9는 결측값)
                def parse_value(value, default=None):
                    try:
                        if value == '-9' or value == '-9.0' or value == '-9.00':
                            return default
                        return float(value)
                    except (ValueError, TypeError):
                        return default
                
                record = {
                    'datetime': parsed_datetime,
                    '기온': parse_value(fields[11]),  # 기온
                    '상대습도': parse_value(fields[13]),  # 상대습도
                    '강수량': parse_value(fields[15], 0),  # 강수량
                    '일조시간': parse_value(fields[33], 0) if len(fields) > 33 else None,  # 일조시간
                    '일사량': parse_value(fields[34], 0) if len(fields) > 34 else None   # 일사량
                }
                
                parsed_data.append(record)
                
            except (ValueError, IndexError):
                continue
        
        if not parsed_data:
            raise ValueError("파싱된 기상 데이터가 없습니다.")
        
        # DataFrame 생성
        df = pd.DataFrame(parsed_data)
        df['datetime_str'] = df['datetime'].dt.strftime('%Y-%m-%d %H:00')
        
        return df
        
    except Exception as e:
        raise Exception(f"기상 데이터 조회 오류: {str(e)}")

def fetch_kma_data_periodically(station_id, start_date, end_date, api_key=DEFAULT_API_KEY):
    """
    기상청 API의 31일 제한을 고려하여 1개월 단위로 나누어 데이터를 수집
    """
    all_weather_data = []

    current_start = start_date
    while current_start <= end_date:
        # 최대 31일 후까지 자르되 end_date를 넘지 않도록
        current_end = min(current_start + timedelta(days=30), end_date)

        try:
            df = fetch_kma_data_simple(station_id, current_start, current_end, api_key)
            all_weather_data.append(df)
        except Exception as e:
            raise Exception(f"{current_start}~{current_end} 기상데이터 오류: {str(e)}")

        current_start = current_end + timedelta(days=1)

    # 모든 구간 데이터를 병합
    if all_weather_data:
        return pd.concat(all_weather_data, ignore_index=True)
    else:
        raise Exception("기상 데이터가 없습니다.")

def convert_df_to_excel_bytes(df: pd.DataFrame) -> BytesIO:
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='통합데이터')
    output.seek(0)
    return output

def get_weather_data_simulation(start_date, end_date):
    """시뮬레이션 기상 데이터 생성"""
    start_datetime = dt.combine(start_date, dt.min.time())
    end_datetime = dt.combine(end_date, dt.max.time().replace(microsecond=0))
    
    datetimes = pd.date_range(start=start_datetime, end=end_datetime, freq='H')
    
    data = []
    for datetime_obj in datetimes:
        month = datetime_obj.month
        hour = datetime_obj.hour
        day_of_year = datetime_obj.timetuple().tm_yday
        
        # 5월 기준 기온 (광주 지역)
        base_temp = 22 + np.sin((day_of_year - 120) * np.pi / 90) * 6
        hour_factor = -4 * np.cos((hour - 14) * np.pi / 12)
        temp = round(base_temp + hour_factor + np.random.normal(0, 2), 1)
        
        # 상대습도
        base_humidity = 65
        humidity_cycle = 20 * np.cos((hour - 14) * np.pi / 12)
        humidity = max(30, min(95, round(base_humidity + humidity_cycle + np.random.normal(0, 10))))
        
        # 강수량 (5월 우기철)
        rain_prob = 0.12
        rainfall = round(np.random.exponential(1.5), 1) if np.random.random() < rain_prob else 0
        
        # 일조시간
        if 6 <= hour <= 18 and rainfall == 0:
            sunshine = round(np.random.uniform(0.7, 1.0), 1)
        else:
            sunshine = 0.0
        
        # 일사량
        solar_radiation = round(sunshine * np.random.uniform(2.5, 4), 2) if sunshine > 0 else 0
        
        record = {
            'datetime': datetime_obj,
            'datetime_str': datetime_obj.strftime('%Y-%m-%d %H:00'),
            '기온': temp,
            '상대습도': humidity,
            '강수량': rainfall,
            '일조시간': sunshine,
            '일사량': solar_radiation
        }
        
        data.append(record)
    
    return pd.DataFrame(data)

def merge_sewage_weather_data(sewage_df, weather_df):
    """
    하수처리장 데이터와 기상 데이터를 시간별로 병합
    """
    # 시간 단위로 정규화 (분 정보 제거)
    sewage_df['datetime_hour'] = sewage_df['datetime'].dt.floor('h')
    weather_df['datetime_hour'] = weather_df['datetime'].dt.floor('h')
    
    # 병합 수행
    merged_df = pd.merge(
        sewage_df,
        weather_df[['datetime_hour', '기온', '상대습도', '강수량', '일조시간', '일사량']],
        on='datetime_hour',
        how='left'
    )
    
    # 기상 데이터가 없는 경우 보간
    weather_cols = ['기온', '상대습도', '강수량', '일조시간', '일사량']
    for col in weather_cols:
        merged_df[col] = merged_df[col].interpolate(method='linear')
    
    return merged_df

def create_combined_analysis_chart(df, sewage_param, weather_param):
    """하수처리장 데이터와 기상 데이터 결합 분석 차트"""
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=[
            f"{SEWAGE_PARAMETERS[sewage_param]['name']} 변화",
            f"{WEATHER_ELEMENTS[weather_param]['name']} 변화"
        ],
        vertical_spacing=0.15
    )
    
    # 하수처리장 데이터
    sewage_col = f"{sewage_param}_측정치"
    if sewage_col in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df['datetime_str'],
                y=df[sewage_col],
                mode='lines',
                name=SEWAGE_PARAMETERS[sewage_param]['name'],
                line=dict(color=SEWAGE_PARAMETERS[sewage_param]['color'], width=2)
            ),
            row=1, col=1
        )
    
    # 기상 데이터
    if weather_param in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df['datetime_str'],
                y=df[weather_param],
                mode='lines',
                name=WEATHER_ELEMENTS[weather_param]['name'],
                line=dict(color=WEATHER_ELEMENTS[weather_param]['color'], width=2)
            ),
            row=2, col=1
        )
    
    fig.update_layout(height=600, showlegend=False)
    fig.update_xaxes(tickangle=45)
    
    return fig

def create_correlation_heatmap(df, sewage_params, weather_params):
    """상관관계 히트맵 생성"""
    # 측정치 컬럼들 선택
    sewage_cols = [f"{param}_측정치" for param in sewage_params if f"{param}_측정치" in df.columns]
    weather_cols = [param for param in weather_params if param in df.columns]
    
    analysis_cols = sewage_cols + weather_cols
    
    if len(analysis_cols) < 2:
        return None
    
    # 상관관계 계산
    corr_data = df[analysis_cols].corr()
    
    # 컬럼명 정리
    display_names = {}
    for col in analysis_cols:
        if col.endswith('_측정치'):
            param = col.replace('_측정치', '')
            display_names[col] = SEWAGE_PARAMETERS.get(param, {}).get('name', param)
        else:
            display_names[col] = WEATHER_ELEMENTS.get(col, {}).get('name', col)
    
    corr_data = corr_data.rename(columns=display_names, index=display_names)
    
    fig = px.imshow(
        corr_data,
        text_auto=True,
        aspect="auto",
        title="하수처리장 측정값과 기상요소 간 상관관계",
        color_continuous_scale="RdBu_r",
        zmin=-1, zmax=1
    )
    
    return fig

def main():
    st.title("🌊 하수처리장 측정데이터 + 기상데이터 통합 분석 시스템")
    st.markdown("---")
    
    # plant_name 기본값을 미리 선언
    plant_name = "하수처리장"
    
    # 사이드바 설정
    with st.sidebar:
        st.header("📁 데이터 업로드")
        
        # 엑셀 파일 업로드
        uploaded_file = st.file_uploader(
            "하수처리장 측정데이터 엑셀 파일을 업로드하세요",
            type=['xlsx', 'xls'],
            help="측정일자, 측정시간, 측정항목별 측정치/상태정보/대체값/대체코드가 포함된 엑셀 파일"
        )
        
        if uploaded_file is not None:
        
            # 예: "측정자료조회-광주광역시-광주제1하수-1 (1).xlsx"
            filename = uploaded_file.name
            try:
                plant_name = filename.split("-")[2]  # "광주제1하수"
            except IndexError:
                plant_name = "하수처리장"  # 예외 발생 시 기본값
        
            try:
                # 엑셀 파일 파싱
                with st.spinner("엑셀 파일을 분석 중입니다..."):
                    sewage_df, title_info, sewage_params = parse_excel_file(uploaded_file)
                
                st.success(f"✅ 엑셀 데이터 로드 완료! ({len(sewage_df)}건)")
                st.info(f"📋 측정항목: {', '.join(sewage_params)}")
                
                # 데이터 기간 확인
                start_date = sewage_df['datetime'].min().date()
                end_date = sewage_df['datetime'].max().date()
                
                st.info(f"📅 데이터 기간: {start_date} ~ {end_date} ({(end_date - start_date).days + 1}일)")
                
                # 기상관측소 선택
                st.subheader("🌤️ 기상관측소 선택")
                station_options = {f"{info['name']} ({station_id})": station_id 
                                 for station_id, info in WEATHER_STATIONS.items()}
                
                selected_station_key = st.selectbox(
                    "기상관측소",
                    options=list(station_options.keys()),
                    index=0  # 광주가 첫 번째
                )
                selected_station_id = station_options[selected_station_key]
                
                # API 설정
                st.subheader("🔑 기상청 API 설정")
                use_real_api = st.checkbox("실제 기상청 API 사용", value=False)
                
                if use_real_api:
                    api_key = st.text_input(
                        "API 인증키",
                        value=DEFAULT_API_KEY,
                        type="password"
                    )
                else:
                    api_key = None
                    st.info("시뮬레이션 기상 데이터를 사용합니다.")
                
                # 데이터 통합 버튼
                if st.button("🔄 기상데이터와 통합", type="primary", use_container_width=True):
                    try:
                        # 기상 데이터 조회
                        data_source = "실제 기상청 API" if use_real_api else "시뮬레이션"
                        
                        with st.spinner(f'{data_source}에서 기상 데이터를 조회하고 있습니다...'):
                            if use_real_api and api_key:
                                weather_df = fetch_kma_data_periodically(selected_station_id, start_date, end_date, api_key)
                            else:
                                weather_df = get_weather_data_simulation(start_date, end_date)                        
                        # 데이터 병합
                        with st.spinner("데이터를 병합하고 있습니다..."):
                            merged_df = merge_sewage_weather_data(sewage_df, weather_df)
                        
                        st.session_state.analysis_data = {
                            'merged_df': merged_df,
                            'sewage_params': sewage_params,
                            'weather_params': list(WEATHER_ELEMENTS.keys()),
                            'station_name': WEATHER_STATIONS[selected_station_id]['name'],
                            'title_info': title_info,
                            'data_source': data_source
                        }
                        
                        st.success(f"✅ 데이터 통합 완료! ({data_source})")
                        
                    except Exception as e:
                        st.error(f"❌ 데이터 통합 실패: {str(e)}")
            
            except Exception as e:
                st.error(f"❌ 엑셀 파일 처리 실패: {str(e)}")
    
    # 메인 컨텐츠
    if 'analysis_data' in st.session_state:
        data = st.session_state.analysis_data
        df = data['merged_df']
        sewage_params = data['sewage_params']
        weather_params = data['weather_params']
        
        # 기본 정보 표시
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("데이터 건수", f"{len(df):,}건")
        with col2:
            st.metric("측정항목", f"{len(sewage_params)}개")
        with col3:
            st.metric("기상요소", f"{len(weather_params)}개")
        with col4:
            st.metric("기상관측소", data['station_name'])
        with col5:
            st.metric("데이터 유형", data['data_source'])
        
        st.markdown("---")
        
        # 탭으로 구분된 분석
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 통합분석", "🔗 상관관계", "📈 시계열", "📋 데이터", "💾 다운로드"])
        
        with tab1:
            st.subheader("하수처리장 측정값과 기상요소 통합 분석")
            
            # 분석할 항목 선택
            col1, col2 = st.columns(2)
            with col1:
                selected_sewage = st.selectbox(
                    "하수처리장 측정항목 선택",
                    options=sewage_params,
                    format_func=lambda x: f"{SEWAGE_PARAMETERS.get(x, {}).get('name', x)} ({SEWAGE_PARAMETERS.get(x, {}).get('unit', '')})"
                )
            
            with col2:
                selected_weather = st.selectbox(
                    "기상요소 선택",
                    options=weather_params,
                    format_func=lambda x: f"{WEATHER_ELEMENTS.get(x, {}).get('name', x)} ({WEATHER_ELEMENTS.get(x, {}).get('unit', '')})"
                )
            
            # 통합 분석 차트
            if selected_sewage and selected_weather:
                chart = create_combined_analysis_chart(df, selected_sewage, selected_weather)
                if chart:
                    st.plotly_chart(chart, use_container_width=True)
                
                # 통계 요약
                st.subheader("통계 요약")
                
                sewage_col = f"{selected_sewage}_측정치"
                weather_col = selected_weather
                
                if sewage_col in df.columns and weather_col in df.columns:
                    # 기본 통계
                    stats_col1, stats_col2 = st.columns(2)
                    
                    with stats_col1:
                        st.markdown(f"**{SEWAGE_PARAMETERS.get(selected_sewage, {}).get('name', selected_sewage)} 통계**")
                        sewage_data = df[sewage_col].dropna()
                        if len(sewage_data) > 0:
                            sewage_data_numeric = pd.to_numeric(sewage_data, errors='coerce')
                            st.write(f"• 평균: {sewage_data_numeric.mean():.2f} {SEWAGE_PARAMETERS.get(selected_sewage, {}).get('unit', '')}")
                            st.write(f"• 최대: {sewage_data_numeric.max():.2f} {SEWAGE_PARAMETERS.get(selected_sewage, {}).get('unit', '')}")
                            st.write(f"• 최소: {sewage_data_numeric.min():.2f} {SEWAGE_PARAMETERS.get(selected_sewage, {}).get('unit', '')}")
                            st.write(f"• 표준편차: {sewage_data_numeric.std():.2f}")
                    
                    with stats_col2:
                        st.markdown(f"**{WEATHER_ELEMENTS.get(selected_weather, {}).get('name', selected_weather)} 통계**")
                        weather_data = df[weather_col].dropna()
                        if len(weather_data) > 0:
                            st.write(f"• 평균: {weather_data.mean():.2f} {WEATHER_ELEMENTS.get(selected_weather, {}).get('unit', '')}")
                            st.write(f"• 최대: {weather_data.max():.2f} {WEATHER_ELEMENTS.get(selected_weather, {}).get('unit', '')}")
                            st.write(f"• 최소: {weather_data.min():.2f} {WEATHER_ELEMENTS.get(selected_weather, {}).get('unit', '')}")
                            st.write(f"• 표준편차: {weather_data.std():.2f}")
                    
                    # 상관계수
                    correlation = df[[sewage_col, weather_col]].corr().iloc[0, 1]
                    if not pd.isna(correlation):
                        st.markdown(f"**상관계수**: {correlation:.3f}")
                        if abs(correlation) > 0.7:
                            st.success("🔴 강한 상관관계")
                        elif abs(correlation) > 0.4:
                            st.warning("🟡 중간 상관관계")
                        else:
                            st.info("🔵 약한 상관관계")
        
        with tab2:
            st.subheader("전체 상관관계 분석")
            
            # 상관관계 히트맵
            heatmap = create_correlation_heatmap(df, sewage_params, weather_params)
            if heatmap:
                st.plotly_chart(heatmap, use_container_width=True)
            
            # 상관관계 테이블
            st.subheader("상관관계 상세 수치")
            
            # 측정치 컬럼들과 기상 요소들 간의 상관관계 계산
            sewage_cols = [f"{param}_측정치" for param in sewage_params if f"{param}_측정치" in df.columns]
            weather_cols = [param for param in weather_params if param in df.columns]
            
            if sewage_cols and weather_cols:
                corr_results = []
                
                for sewage_col in sewage_cols:
                    param_name = sewage_col.replace('_측정치', '')
                    sewage_name = SEWAGE_PARAMETERS.get(param_name, {}).get('name', param_name)
                    
                    for weather_col in weather_cols:
                        weather_name = WEATHER_ELEMENTS.get(weather_col, {}).get('name', weather_col)
                        
                        # 상관계수 계산
                        # Ensure both columns have at least two valid numeric values
                        sewage_series = pd.to_numeric(df[sewage_col], errors='coerce')
                        weather_series = pd.to_numeric(df[weather_col], errors='coerce')
                        valid_mask = sewage_series.notna() & weather_series.notna()
                        if valid_mask.sum() >= 2:
                            corr_value = sewage_series[valid_mask].corr(weather_series[valid_mask])
                        else:
                            corr_value = np.nan
                        
                        if not pd.isna(corr_value):
                            corr_results.append({
                                '하수처리장 측정항목': sewage_name,
                                '기상요소': weather_name,
                                '상관계수': round(corr_value, 4),
                                '상관강도': '강함' if abs(corr_value) > 0.7 else '중간' if abs(corr_value) > 0.4 else '약함'
                            })
                
                if corr_results:
                    corr_df = pd.DataFrame(corr_results)
                    corr_df = corr_df.sort_values('상관계수', key=abs, ascending=False)
                    st.dataframe(corr_df, use_container_width=True)
        
        with tab3:
            st.subheader("시계열 분석")
            
            # 다중 선택을 위한 컬럼 구성
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**하수처리장 측정항목 선택**")
                selected_sewage_multi = []
                for param in sewage_params:
                    if st.checkbox(
                        f"{SEWAGE_PARAMETERS.get(param, {}).get('name', param)}",
                        key=f"sewage_{param}",
                        value=param == sewage_params[0]  # 첫 번째만 기본 선택
                    ):
                        selected_sewage_multi.append(param)
            
            with col2:
                st.markdown("**기상요소 선택**")
                selected_weather_multi = []
                for param in weather_params:
                    if st.checkbox(
                        f"{WEATHER_ELEMENTS.get(param, {}).get('name', param)}",
                        key=f"weather_{param}",
                        value=param == '기온'  # 기온만 기본 선택
                    ):
                        selected_weather_multi.append(param)
            
            # 시계열 차트 생성
            if selected_sewage_multi or selected_weather_multi:
                total_plots = len(selected_sewage_multi) + len(selected_weather_multi)
                
                fig = make_subplots(
                    rows=total_plots, cols=1,
                    subplot_titles=[
                        *[f"{SEWAGE_PARAMETERS.get(param, {}).get('name', param)} 변화" for param in selected_sewage_multi],
                        *[f"{WEATHER_ELEMENTS.get(param, {}).get('name', param)} 변화" for param in selected_weather_multi]
                    ],
                    vertical_spacing=0.08
                )
                
                row_idx = 1
                
                # 하수처리장 데이터 플롯
                for param in selected_sewage_multi:
                    col_name = f"{param}_측정치"
                    if col_name in df.columns:
                        fig.add_trace(
                            go.Scatter(
                                x=df['datetime_str'],
                                y=df[col_name],
                                mode='lines',
                                name=SEWAGE_PARAMETERS.get(param, {}).get('name', param),
                                line=dict(color=SEWAGE_PARAMETERS.get(param, {}).get('color', '#333333'), width=1.5)
                            ),
                            row=row_idx, col=1
                        )
                        fig.update_yaxes(
                            title_text=f"{SEWAGE_PARAMETERS.get(param, {}).get('name', param)} ({SEWAGE_PARAMETERS.get(param, {}).get('unit', '')})",
                            row=row_idx, col=1
                        )
                        row_idx += 1
                
                # 기상 데이터 플롯
                for param in selected_weather_multi:
                    if param in df.columns:
                        fig.add_trace(
                            go.Scatter(
                                x=df['datetime_str'],
                                y=df[param],
                                mode='lines',
                                name=WEATHER_ELEMENTS.get(param, {}).get('name', param),
                                line=dict(color=WEATHER_ELEMENTS.get(param, {}).get('color', '#666666'), width=1.5)
                            ),
                            row=row_idx, col=1
                        )
                        fig.update_yaxes(
                            title_text=f"{WEATHER_ELEMENTS.get(param, {}).get('name', param)} ({WEATHER_ELEMENTS.get(param, {}).get('unit', '')})",
                            row=row_idx, col=1
                        )
                        row_idx += 1
                
                fig.update_layout(
                    height=300 * total_plots,
                    showlegend=False,
                    title_text="시간별 변화 추이"
                )
                fig.update_xaxes(tickangle=45)
                
                st.plotly_chart(fig, use_container_width=True)
            
            # 일별/시간별 패턴 분석
            if len(df) > 48:  # 2일 이상 데이터
                st.subheader("패턴 분석")
                
                pattern_type = st.radio("분석 유형", ["시간별 패턴", "일별 패턴"])
                
                if pattern_type == "시간별 패턴":
                    # 시간별 평균 계산
                    df['hour'] = df['datetime'].dt.hour

                    # 숫자형 컬럼만 집계
                    numeric_cols = []
                    for param in sewage_params:
                        col = f"{param}_측정치"
                        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
                            numeric_cols.append(col)
                    for param in weather_params:
                        if param in df.columns and pd.api.types.is_numeric_dtype(df[param]):
                            numeric_cols.append(param)

                    # 👉 집계 전 숫자형 변환
                    for col in numeric_cols:
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                    agg_dict = {col: 'mean' for col in numeric_cols}
                    hourly_pattern = df.groupby('hour').agg(agg_dict).reset_index()
                    
                    # 선택된 항목들의 시간별 패턴 차트
                    if selected_sewage_multi or selected_weather_multi:
                        pattern_fig = go.Figure()
                        
                        for param in selected_sewage_multi:
                            col_name = f"{param}_측정치"
                            if col_name in hourly_pattern.columns:
                                pattern_fig.add_trace(go.Scatter(
                                    x=hourly_pattern['hour'],
                                    y=hourly_pattern[col_name],
                                    mode='lines+markers',
                                    name=f"{SEWAGE_PARAMETERS.get(param, {}).get('name', param)} (하수)",
                                    line=dict(color=SEWAGE_PARAMETERS.get(param, {}).get('color', '#333333'))
                                ))
                        
                        for param in selected_weather_multi:
                            if param in hourly_pattern.columns:
                                pattern_fig.add_trace(go.Scatter(
                                    x=hourly_pattern['hour'],
                                    y=hourly_pattern[param],
                                    mode='lines+markers',
                                    name=f"{WEATHER_ELEMENTS.get(param, {}).get('name', param)} (기상)",
                                    line=dict(color=WEATHER_ELEMENTS.get(param, {}).get('color', '#666666')),
                                    yaxis='y2'
                                ))
                        
                        pattern_fig.update_layout(
                            title="시간별 평균 패턴",
                            xaxis_title="시간 (시)",
                            yaxis_title="하수처리장 측정값",
                            yaxis2=dict(title="기상값", overlaying='y', side='right'),
                            height=500
                        )
                        
                        st.plotly_chart(pattern_fig, use_container_width=True)
                
                else:  # 일별 패턴
                    df['date'] = df['datetime'].dt.date
                    daily_pattern = df.groupby('date').agg({
                        **{f"{param}_측정치": 'mean' for param in sewage_params if f"{param}_측정치" in df.columns},
                        **{param: 'mean' for param in weather_params if param in df.columns}
                    }).reset_index()
                    
                    if selected_sewage_multi or selected_weather_multi:
                        daily_fig = go.Figure()
                        
                        for param in selected_sewage_multi:
                            col_name = f"{param}_측정치"
                            if col_name in daily_pattern.columns:
                                daily_fig.add_trace(go.Scatter(
                                    x=daily_pattern['date'],
                                    y=daily_pattern[col_name],
                                    mode='lines+markers',
                                    name=f"{SEWAGE_PARAMETERS.get(param, {}).get('name', param)} (하수)",
                                    line=dict(color=SEWAGE_PARAMETERS.get(param, {}).get('color', '#333333'))
                                ))
                        
                        for param in selected_weather_multi:
                            if param in daily_pattern.columns:
                                daily_fig.add_trace(go.Scatter(
                                    x=daily_pattern['date'],
                                    y=daily_pattern[param],
                                    mode='lines+markers',
                                    name=f"{WEATHER_ELEMENTS.get(param, {}).get('name', param)} (기상)",
                                    line=dict(color=WEATHER_ELEMENTS.get(param, {}).get('color', '#666666')),
                                    yaxis='y2'
                                ))
                        
                        daily_fig.update_layout(
                            title="일별 평균 패턴",
                            xaxis_title="날짜",
                            yaxis_title="하수처리장 측정값",
                            yaxis2=dict(title="기상값", overlaying='y', side='right'),
                            height=500
                        )
                        
                        st.plotly_chart(daily_fig, use_container_width=True)
        
        with tab4:
            st.subheader("통합 데이터 테이블")
            
            # 컬럼 선택 옵션
            col1, col2, col3 = st.columns(3)
            
            with col1:
                show_basic = st.checkbox("기본 정보", value=True)
                show_sewage = st.checkbox("하수처리장 측정값", value=True)
                show_weather = st.checkbox("기상 데이터", value=True)
            
            with col2:
                rows_per_page = st.selectbox("페이지당 행 수", [25, 50, 100, 200], index=1)
            
            with col3:
                if len(df) > 100:
                    available_dates = sorted(df['datetime'].dt.date.unique())
                    selected_date = st.selectbox(
                        "날짜 필터 (선택사항)",
                        options=['전체'] + [str(d) for d in available_dates],
                        index=0
                    )
                else:
                    selected_date = '전체'
            
            # 표시할 컬럼 구성
            display_columns = []
            
            if show_basic:
                display_columns.extend(['datetime_str', '방류구'])
            
            if show_sewage:
                for param in sewage_params:
                    display_columns.extend([
                        f"{param}_측정치",
                        f"{param}_상태정보",
                        f"{param}_대체값",
                        f"{param}_대체코드"
                    ])
            
            if show_weather:
                display_columns.extend(['기온', '상대습도', '강수량', '일조시간', '일사량'])
            
            # 존재하는 컬럼만 필터링
            display_columns = [col for col in display_columns if col in df.columns]
            
            # 데이터 필터링
            filtered_df = df.copy()
            if selected_date != '전체':
                filtered_df = filtered_df[filtered_df['datetime'].dt.date == pd.to_datetime(selected_date).date()]
            
            # 데이터 표시
            if display_columns:
                display_df = filtered_df[display_columns].copy()
                
                # 페이지네이션
                total_rows = len(display_df)
                total_pages = (total_rows - 1) // rows_per_page + 1
                
                if total_pages > 1:
                    page = st.selectbox(f"페이지 선택 (총 {total_pages}페이지)", range(1, total_pages + 1))
                    start_idx = (page - 1) * rows_per_page
                    end_idx = min(start_idx + rows_per_page, total_rows)
                    display_df = display_df.iloc[start_idx:end_idx]
                
                # 컬럼명 한글화
                column_rename = {}
                for col in display_df.columns:
                    if col == 'datetime_str':
                        column_rename[col] = '측정일시'
                    elif col == '방류구':
                        column_rename[col] = '방류구'
                    elif col.endswith('_측정치'):
                        param = col.replace('_측정치', '')
                        column_rename[col] = f"{SEWAGE_PARAMETERS.get(param, {}).get('name', param)}"
                    elif col.endswith('_상태정보'):
                        param = col.replace('_상태정보', '')
                        column_rename[col] = f"{SEWAGE_PARAMETERS.get(param, {}).get('name', param)}_상태"
                    elif col.endswith('_대체값'):
                        param = col.replace('_대체값', '')
                        column_rename[col] = f"{SEWAGE_PARAMETERS.get(param, {}).get('name', param)}_대체값"
                    elif col.endswith('_대체코드'):
                        param = col.replace('_대체코드', '')
                        column_rename[col] = f"{SEWAGE_PARAMETERS.get(param, {}).get('name', param)}_대체코드"
                    elif col in WEATHER_ELEMENTS:
                        column_rename[col] = f"{WEATHER_ELEMENTS[col]['name']}({WEATHER_ELEMENTS[col]['unit']})"
                
                display_df = display_df.rename(columns=column_rename)
                
                st.dataframe(display_df, use_container_width=True)
                st.caption(f"총 {total_rows:,}개 행 중 {len(display_df)}개 행 표시")
        
        with tab5:
            st.subheader("데이터 다운로드")
            
            # 다운로드 옵션
            col1, col2 = st.columns(2)
            
            with col1:
                # 전체 통합 데이터 CSV 다운로드
                csv_data = df.to_csv(index=False, encoding='utf-8-sig')
                # st.download_button(
                #     label="📄 전체 통합데이터 CSV 다운로드",
                #     data=csv_data,
                #     file_name=f"하수처리장_기상데이터_통합_{df['datetime'].min().strftime('%Y%m%d')}_{df['datetime'].max().strftime('%Y%m%d')}.csv",
                #     mime="text/csv",
                #     use_container_width=True
                # )

                # 처리장 명칭 추출 (예: 데이터의 제목 row 또는 별도 항목에서 추출)
                

                # 파일명 생성
                excel_filename = f"{plant_name}_기상데이터_통합_{df['datetime'].min().strftime('%Y%m%d')}_{df['datetime'].max().strftime('%Y%m%d')}.xlsx"

                excel_data = convert_df_to_excel_bytes(df)
                st.download_button(
                    label="📄 전체 통합데이터 Excel 다운로드",
                    data=excel_data,
                    file_name= excel_filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
           
            
            with col2:
                # 요약 통계 다운로드
                summary_data = []
                
                # 하수처리장 데이터 요약
                for param in sewage_params:
                    col_name = f"{param}_측정치"
                    if col_name in df.columns:
                        param_data = df[col_name].dropna()
                        # 숫자 변환 추가
                        param_data_numeric = pd.to_numeric(param_data, errors='coerce').dropna()
                        if len(param_data_numeric) > 0:
                            summary_data.append({
                                '구분': '하수처리장',
                                '항목': SEWAGE_PARAMETERS.get(param, {}).get('name', param),
                                '단위': SEWAGE_PARAMETERS.get(param, {}).get('unit', ''),
                                '평균': round(param_data_numeric.mean(), 3),
                                '최대': round(param_data_numeric.max(), 3),
                                '최소': round(param_data_numeric.min(), 3),
                                '표준편차': round(param_data_numeric.std(), 3)
                            })
                
                # 기상 데이터 요약
                for param in weather_params:
                    if param in df.columns:
                        param_data = df[param].dropna()
                        param_data_numeric = pd.to_numeric(param_data, errors='coerce').dropna()
                        if len(param_data_numeric) > 0:
                            summary_data.append({
                                '구분': '기상',
                                '항목': WEATHER_ELEMENTS.get(param, {}).get('name', param),
                                '단위': WEATHER_ELEMENTS.get(param, {}).get('unit', ''),
                                '평균': round(param_data_numeric.mean(), 3),
                                '최대': round(param_data_numeric.max(), 3),
                                '최소': round(param_data_numeric.min(), 3),
                                '표준편차': round(param_data_numeric.std(), 3)
                            })
                
                if summary_data:
                    summary_df = pd.DataFrame(summary_data)
                    summary_csv = summary_df.to_csv(index=False, encoding='utf-8-sig')
                    
                    # st.download_button(
                    #     label="📊 요약통계 CSV 다운로드",
                    #     data=summary_csv,
                    #     file_name=f"하수처리장_기상데이터_요약통계_{df['datetime'].min().strftime('%Y%m%d')}.csv",
                    #     mime="text/csv",
                    #     use_container_width=True
                    # )

                    summary_excel = convert_df_to_excel_bytes(summary_df)
                    st.download_button(
                        label="📊 요약통계 Excel 다운로드",
                        data=summary_excel,
                        file_name=f"하수처리장_기상데이터_요약통계_{df['datetime'].min().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )


            # 선별 다운로드 옵션
            st.markdown("**선별 다운로드**")
            
            col3, col4 = st.columns(2)
            
            with col3:
                # 하수처리장 측정값만
                sewage_cols = ['datetime_str', '방류구'] + [f"{param}_측정치" for param in sewage_params if f"{param}_측정치" in df.columns]
                sewage_only_df = df[sewage_cols]
                sewage_csv = sewage_only_df.to_csv(index=False, encoding='utf-8-sig')
                
                st.download_button(
                    label="🏭 하수처리장 측정값만 CSV",
                    data=sewage_csv,
                    file_name=f"하수처리장_측정값_{df['datetime'].min().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            
            with col4:
                # 기상 데이터만
                weather_cols = ['datetime_str'] + [param for param in weather_params if param in df.columns]
                weather_only_df = df[weather_cols]
                weather_csv = weather_only_df.to_csv(index=False, encoding='utf-8-sig')
                
                st.download_button(
                    label="🌤️ 기상데이터만 CSV",
                    data=weather_csv,
                    file_name=f"기상데이터_{data['station_name']}_{df['datetime'].min().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            
            # JSON 다운로드
            st.markdown("**JSON 형식 다운로드**")
            
            json_data = {
                "metadata": {
                    "title": data['title_info'],
                    "station_name": data['station_name'],
                    "data_source": data['data_source'],
                    "start_date": df['datetime'].min().strftime('%Y-%m-%d %H:%M:%S'),
                    "end_date": df['datetime'].max().strftime('%Y-%m-%d %H:%M:%S'),
                    "total_records": len(df),
                    "sewage_parameters": sewage_params,
                    "weather_parameters": weather_params
                },
                "data": []
            }
            
            # DataFrame을 JSON으로 변환
            for _, row in df.iterrows():
                record = {}
                for col in df.columns:
                    value = row[col]
                    if isinstance(value, pd.Timestamp):
                        record[col] = value.strftime('%Y-%m-%d %H:%M:%S')
                    elif pd.isna(value):
                        record[col] = None
                    elif isinstance(value, (np.integer, np.floating)):
                        record[col] = float(value) if not pd.isna(value) else None
                    else:
                        record[col] = value
                json_data["data"].append(record)
            
            json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
            
            st.download_button(
                label="📋 전체 데이터 JSON 다운로드",
                data=json_str,
                file_name=f"하수처리장_기상데이터_통합_{df['datetime'].min().strftime('%Y%m%d')}.json",
                mime="application/json",
                use_container_width=True
            )
            
            # 데이터 포맷 안내
            st.markdown("---")
            with st.expander("📋 데이터 포맷 정보"):
                st.markdown("""
                **통합 데이터 포맷:**
                
                **기본 정보**
                - `datetime_str`: 측정 일시 (YYYY-MM-DD HH:MM:SS)
                - `방류구`: 방류구 번호
                - `date`: 측정 날짜
                - `time`: 측정 시간
                
                **하수처리장 측정 항목** (각 항목별로 4개 컬럼)
                - `{항목명}_측정치`: 실제 측정값
                - `{항목명}_상태정보`: 장비 상태 (예: "장비정상")
                - `{항목명}_대체값`: 대체값 (있는 경우)
                - `{항목명}_대체코드`: 대체 코드 (있는 경우)
                
                **기상 데이터**
                - `TA`: 기온 (°C)
                - `HM`: 상대습도 (%)
                - `RN`: 강수량 (mm)
                - `SS`: 일조시간 (hr)
                - `SI`: 일사량 (MJ/m²)
                
                **주의사항:**
                - 결측값은 None 또는 빈 값으로 표시
                - 기상 데이터는 시간 단위로 하수처리장 데이터와 매칭
                - 상관관계 분석은 측정치만 사용
                """)
    
    else:
        # 초기 화면
        st.info("👈 좌측 사이드바에서 하수처리장 측정데이터 엑셀 파일을 업로드하세요.")
        
        # 서비스 소개
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("""
            ### 📊 데이터 통합 분석
            - 하수처리장 측정값과 기상데이터 결합
            - 시간별 자동 매칭 및 보간
            - 상관관계 및 패턴 분석
            """)
        
        with col2:
            st.markdown("""
            ### 🌤️ 기상청 API 연동
            - 실제 기상관측소 데이터 활용
            - 기온, 습도, 강수량, 일조시간, 일사량
            - 시뮬레이션 데이터 대체 지원
            """)
        
        with col3:
            st.markdown("""
            ### 📈 다양한 분석 도구
            - 시계열 변화 추이 분석
            - 시간별/일별 패턴 분석
            - 상관관계 히트맵 및 통계
            """)
        
        st.markdown("---")
        
        # 지원 파일 형식 안내
        st.subheader("📁 지원 파일 형식")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("""
            **엑셀 파일 구조 예시:**
            - 1행: 제목 정보 (예: "광주제1하수(1방류구)2025/05/01 00시 ~ 2025/05/31 23시")
            - 2행: 항목별 헤더 (방류구, 측정일자, 측정시간, TOC(mg/L), SS(mg/L), ...)
            - 3행: 세부 헤더 (기준치, 측정치, 상태정보, 대체값, 대체코드)
            - 4행부터: 실제 측정 데이터
            """)
        
        with col2:
            st.markdown("""
            **지원 측정 항목:**
            - TOC (총유기탄소)
            - SS (부유물질)
            - T-N (총질소)
            - T-P (총인)
            - pH (수소이온농도)
            - 적산유량
            """)
        
        # 기상 요소 소개
        st.subheader("🌡️ 제공 기상요소")
        
        weather_col1, weather_col2, weather_col3, weather_col4, weather_col5 = st.columns(5)
        
        with weather_col1:
            st.markdown("""
            **기온 (TA)**
            - 단위: °C
            - 시간별 측정값
            - 하수처리 효율과 상관관계
            """)
        
        with weather_col2:
            st.markdown("""
            **상대습도 (HM)**
            - 단위: %
            - 대기 중 수분 함량
            - 증발량 영향 분석
            """)
        
        with weather_col3:
            st.markdown("""
            **강수량 (RN)**
            - 단위: mm
            - 시간당 강수량
            - 유입량 변화 분석
            """)
        
        with weather_col4:
            st.markdown("""
            **일조시간 (SS)**
            - 단위: hr
            - 햇빛 조사 시간
            - 미생물 활성 영향
            """)
        
        with weather_col5:
            st.markdown("""
            **일사량 (SI)**
            - 단위: MJ/m²
            - 태양 복사 에너지
            - 수온 변화 영향
            """)
        
        # 샘플 데이터 미리보기
        st.markdown("---")
        st.subheader("📋 통합 데이터 샘플")
        
        # 샘플 데이터 생성
        sample_data = {
            '측정일시': ['2025-05-01 00:00', '2025-05-01 01:00', '2025-05-01 02:00', '2025-05-01 03:00'],
            '방류구': [1, 1, 1, 1],
            'TOC_측정치': [6.9, 7.0, 6.9, 6.9],
            'TOC_상태정보': ['장비정상', '장비정상', '장비정상', '장비정상'],
            'SS_측정치': [3.4, 3.4, 3.4, 3.4],
            'pH_측정치': [6.4, 6.4, 6.4, 6.4],
            '기온(°C)': [18.5, 17.8, 17.2, 16.9],
            '상대습도(%)': [72, 75, 78, 80],
            '강수량(mm)': [0.0, 0.0, 0.0, 0.0],
            '일조시간(hr)': [0.0, 0.0, 0.0, 0.0]
        }
        
        sample_df = pd.DataFrame(sample_data)
        st.dataframe(sample_df, use_container_width=True)
        st.caption("하수처리장 측정데이터와 기상데이터 통합 샘플")
        
        
if __name__ == "__main__":
    main()
