import sys
import subprocess
import importlib.metadata
import os

# --- AUTO-INSTALADOR DE DEPENDÊNCIAS ---
def check_and_install_requirements():
    try:
        with open('requirements.txt', 'r') as f:
            requirements = [line.strip() for line in f if line.strip()]
        
        installed = {dist.metadata['Name'].lower() for dist in importlib.metadata.distributions()}
        missing = []
        
        for req in requirements:
            pkg_name = req.split('==')[0].split('>')[0].split('<')[0].lower()
            if pkg_name not in installed:
                missing.append(req)
                
        if missing:
            print(f"Instalando bibliotecas ausentes: {', '.join(missing)}...")
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', *missing])
    except Exception as e:
        pass

check_and_install_requirements()
# ---------------------------------------

import streamlit as st
from PIL import Image
from streamlit_drawable_canvas import st_canvas

st.set_page_config(page_title="Prancheta Tática CS2", layout="wide", page_icon="🗺️")

st.title("🗺️ Motor 2 — Prancheta Tática")
st.markdown("Desenhe suas execuções, setups e posicionamentos em cima dos mapas.")

# --- GARANTINDO A PASTA DE MAPAS ---
PASTA_MAPAS = "mapas"
if not os.path.exists(PASTA_MAPAS):
    os.makedirs(PASTA_MAPAS)
    st.warning(f"⚠️ Criei uma pasta chamada '{PASTA_MAPAS}' no seu projeto. Coloque as imagens dos radares lá dentro!")

# Lendo os mapas disponíveis na pasta
mapas_disponiveis = [f for f in os.listdir(PASTA_MAPAS) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]

# --- SIDEBAR: FERRAMENTAS DA PRANCHETA ---
with st.sidebar:
    st.header("1. Escolha o Mapa")
    if not mapas_disponiveis:
        st.error(f"Nenhum mapa encontrado na pasta '{PASTA_MAPAS}'.")
        mapa_selecionado = None
    else:
        mapa_selecionado = st.selectbox("Mapa:", mapas_disponiveis)
    
    st.divider()
    
    st.header("2. Ferramentas")
    # Dicionário mapeando a ferramenta para a cor e o modo de desenho
    ferramentas = {
        "🚶 Desenhar Rota Livre": {"modo": "freedraw", "cor": "#FFFFFF", "tamanho": 3},
        "📏 Linha Reta": {"modo": "line", "cor": "#FFFFFF", "tamanho": 3},
        "🔵 Jogador CT": {"modo": "point", "cor": "#00BFFF", "tamanho": 12},
        "🟡 Jogador TR": {"modo": "point", "cor": "#FFD700", "tamanho": 12},
        "💨 Smoke": {"modo": "point", "cor": "#A9A9A9", "tamanho": 18},
        "🔥 Molotov": {"modo": "point", "cor": "#FF4500", "tamanho": 18},
        "☀️ Flashbang": {"modo": "point", "cor": "#FFFFFF", "tamanho": 15},
        "💥 HE Grenade": {"modo": "point", "cor": "#228B22", "tamanho": 15},
        "❌ Apagar (Borracha)": {"modo": "freedraw", "cor": "#000000", "tamanho": 20} # Apaga pintando sobreposto se necessário, ou use o botão de lixeira no canvas
    }
    
    escolha_ferramenta = st.radio("Selecione o que inserir:", list(ferramentas.keys()))
    
    cfg = ferramentas[escolha_ferramenta]
    
    # Se for rota ou linha, permite escolher a cor
    if cfg["modo"] in ["freedraw", "line"] and escolha_ferramenta != "❌ Apagar (Borracha)":
        cor_personalizada = st.color_picker("Cor da linha:", cfg["cor"])
        stroke_color = cor_personalizada
    else:
        stroke_color = cfg["cor"]

    st.divider()
    st.caption("💡 Dica: Para apagar o último traço/ponto, use o botão de 'Voltar' (seta) que fica no canto esquerdo embaixo da imagem.")

# --- RENDERIZAÇÃO DA PRANCHETA ---
if mapa_selecionado:
    # Carrega a imagem do mapa
    caminho_imagem = os.path.join(PASTA_MAPAS, mapa_selecionado)
    img = Image.open(caminho_imagem)
    
    # Redimensiona para caber bem na tela (ex: largura fixa de 800px) mantendo proporção
    basewidth = 800
    wpercent = (basewidth / float(img.size[0]))
    hsize = int((float(img.size[1]) * float(wpercent)))
    img_resized = img.resize((basewidth, hsize), Image.Resampling.LANCZOS)
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Instancia o Canvas
        canvas_result = st_canvas(
            fill_color=stroke_color,      # Cor de preenchimento (usada nos pontos)
            stroke_color=stroke_color,    # Cor da borda/linha
            stroke_width=cfg["tamanho"],  # Espessura
            background_image=img_resized, # Imagem de fundo
            update_streamlit=True,
            height=hsize,
            width=basewidth,
            drawing_mode=cfg["modo"],     # 'freedraw', 'line', ou 'point'
            point_display_radius=cfg["tamanho"] if cfg["modo"] == "point" else 0,
            key="prancheta",
        )
    
    with col2:
        st.subheader("Legenda")
        st.markdown("""
        - 🔵 **CT:** Azul
        - 🟡 **TR:** Amarelo
        - 💨 **Smoke:** Cinza (Grande)
        - 🔥 **Molotov:** Laranja (Grande)
        - ☀️ **Flash:** Branco (Médio)
        - 💥 **HE:** Verde (Médio)
        """)
        
        # Botão para exportar os dados desenhados (útil se depois quiser salvar no BD)
        if canvas_result.json_data is not None:
            objetos = canvas_result.json_data["objects"]
            if len(objetos) > 0:
                st.success(f"{len(objetos)} elementos desenhados.")