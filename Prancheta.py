# -*- coding: utf-8 -*-
"""
Prancheta Tática CS2 — versão 2, reconstruída em cima de streamlit-image-
coordinates em vez do streamlit-drawable-canvas (que tinha o problema de
versão que a gente já resolveu no app antigo, mas que no toque do celular
continua meio travado por natureza).

Modelo de interação (tipo prancheta de futebol digital):
- Marcadores CT 1-5 e TR 1-5 são fixos e numerados — cada um só existe uma
  vez no tabuleiro; tocar de novo com ele selecionado MOVE ele.
- Utilitários (Smoke/Flash/HE/Molotov) podem ter várias unidades.
- Três modos: Posicionar / Mover / Apagar (ver barra lateral).

Testado (sintaticamente e com dados sintéticos) neste ambiente; a única
coisa que só dá pra confirmar de verdade no seu celular é a sensação do
toque em si.

Como rodar:
    pip install -r requirements_v2.txt
    streamlit run prancheta.py
"""
from __future__ import annotations

from streamlit_drawable_canvas import st_canvas
import json
import math
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:
    import imageio.v3 as iio
    IMAGEIO_OK = True
except ImportError:
    IMAGEIO_OK = False


import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import streamlit.components.v1 as components
from streamlit_image_coordinates import streamlit_image_coordinates

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False

BASE_DIR = Path(__file__).resolve().parent
MAPS_DIR = BASE_DIR / "maps"
JOGADAS_DIR = BASE_DIR / "minhas_jogadas"
for pasta in [MAPS_DIR, JOGADAS_DIR / "CT", JOGADAS_DIR / "TR"]:
    pasta.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="CS2 Táticas", layout="wide", initial_sidebar_state="collapsed")

st.markdown('''
    <style>
    .block-container { padding: 3rem 0.2rem 0.5rem 0.2rem !important; max-width: 100%; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {background-color: transparent !important;}
    body { user-select: none; -webkit-user-select: none; }
    img { touch-action: none !important; }
    </style>
''', unsafe_allow_html=True)

components.html(
    '''
    <script>
    try {
        const meta = window.parent.document.querySelector('meta[name=viewport]');
        if (meta) {
            meta.setAttribute('content', 'width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes');
        }
    } catch (e) {}
    </script>
    ''',
    height=0, width=0,
)

# ============================================================================
# TOKENS — predefinidos, numerados, estilo prancheta de futebol.
# ============================================================================
TOKENS: dict[str, dict] = {}
for i in range(1, 6):
    TOKENS[f"CT {i}"] = {"grupo": "CT", "rotulo": str(i), "singleton": True,
                          "cor": (40, 110, 220), "texto": (255, 255, 255)}
    TOKENS[f"TR {i}"] = {"grupo": "TR", "rotulo": str(i), "singleton": True,
                          "cor": (230, 190, 40), "texto": (30, 30, 30)}
TOKENS["Smoke"] = {"grupo": "UTIL", "rotulo": "S", "singleton": False, "cor": (200, 200, 200), "texto": (20, 20, 20)}
TOKENS["Flash"] = {"grupo": "UTIL", "rotulo": "F", "singleton": False, "cor": (255, 225, 60), "texto": (20, 20, 20)}
TOKENS["HE"] = {"grupo": "UTIL", "rotulo": "H", "singleton": False, "cor": (110, 210, 110), "texto": (20, 50, 20)}
TOKENS["Molotov"] = {"grupo": "UTIL", "rotulo": "M", "singleton": False, "cor": (230, 90, 40), "texto": (255, 255, 255)}

RAIO_MARCADOR = 16
LIMIAR_PROXIMIDADE_FRAC = 0.045  # % da menor dimensão da imagem pra "achar" um marcador com o toque

ROUND_TYPES = ["Eco", "Forçado", "Comprado"]
ROUND_TYPE_SLUGS = {"Eco": "eco", "Forçado": "forcado", "Comprado": "comprado"}


def font(size: int):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


# ============================================================================
# ESTADO
# ============================================================================
if "markers" not in st.session_state:
    st.session_state.markers = []  # cada item: {uid, tipo, x, y} (x,y em pixels da imagem ORIGINAL)
if "modo" not in st.session_state:
    st.session_state.modo = "Posicionar"
if "marcador_segurando" not in st.session_state:
    st.session_state.marcador_segurando = None
if "ultimo_click_ts" not in st.session_state:
    st.session_state.ultimo_click_ts = None
if "fundo_cache" not in st.session_state:
    st.session_state.fundo_cache = {}  # key -> imagem PIL (mapa + filtro, sem marcadores)
if "desenhos" not in st.session_state:
    st.session_state.desenhos = []

if "cor_pincel" not in st.session_state:
    st.session_state.cor_pincel = "#FF0000"

if "tamanho_pincel" not in st.session_state:
    st.session_state.tamanho_pincel = 4

if "ponto_seta" not in st.session_state:
    st.session_state.ponto_seta = None

def aplicar_filtro_esboco(imagem_pil: Image.Image) -> Image.Image:
    if not CV2_OK:
        return imagem_pil
    img_cv = np.array(imagem_pil.convert('RGB'))
    gray = cv2.cvtColor(img_cv, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    dark_bg = cv2.convertScaleAbs(blurred, alpha=0.3, beta=15)
    edges = cv2.Canny(blurred, 30, 90)
    kernel = np.ones((2, 2), np.uint8)
    edges_dilated = cv2.dilate(edges, kernel, iterations=1)
    esboco = cv2.addWeighted(dark_bg, 0.7, edges_dilated, 0.6, 0)
    return Image.fromarray(cv2.cvtColor(esboco, cv2.COLOR_GRAY2RGB))


def get_fundo(caminho_mapa: Path, modo_esboco: bool) -> Image.Image:
    key = f"{caminho_mapa}_{modo_esboco}"

    if key not in st.session_state.fundo_cache:
        extensao = caminho_mapa.suffix.lower()

        if extensao == ".dds":
            if not IMAGEIO_OK:
                raise RuntimeError(
                    "Para abrir mapas DDS, instale o pacote imageio com: "
                    "pip install imageio"
                )

            # Lê o DDS e transforma em imagem PIL
            img_array = iio.imread(caminho_mapa)
            img = Image.fromarray(img_array).convert("RGB")

        else:
            img = Image.open(caminho_mapa).convert("RGB")

        if modo_esboco:
            img = aplicar_filtro_esboco(img)

        # Guarda somente o último mapa processado
        st.session_state.fundo_cache = {key: img}

    return st.session_state.fundo_cache[key]


def desenhar_marcadores(fundo: Image.Image, markers: list[dict], segurando_uid: str | None) -> Image.Image:
    img = fundo.copy().convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    fnt = font(16)
    for m in markers:
        info = TOKENS.get(m["tipo"])
        if not info:
            continue
        x, y = m["x"], m["y"]
        r = RAIO_MARCADOR
        halo = (255, 255, 255, 255) if m["uid"] == segurando_uid else (0, 0, 0, 200)
        largura_contorno = 4 if m["uid"] == segurando_uid else 2
        draw.ellipse([x - r, y - r, x + r, y + r], fill=info["cor"] + (235,), outline=halo, width=largura_contorno)
        w = draw.textlength(info["rotulo"], font=fnt)
        draw.text((x - w / 2, y - 10), info["rotulo"], font=fnt, fill=info["texto"] + (255,))
    return Image.alpha_composite(img, overlay).convert("RGB")


def distancia(m: dict, x: float, y: float) -> float:
    return math.hypot(m["x"] - x, m["y"] - y)


def marcador_mais_proximo(x: float, y: float, limiar_px: float) -> dict | None:
    candidatos = [(distancia(m, x, y), m) for m in st.session_state.markers]
    candidatos = [c for c in candidatos if c[0] <= limiar_px]
    if not candidatos:
        return None
    return min(candidatos, key=lambda c: c[0])[1]


def colocar_ou_mover(tipo: str, x: float, y: float):
    info = TOKENS[tipo]
    if info["singleton"]:
        for m in st.session_state.markers:
            if m["tipo"] == tipo:
                m["x"], m["y"] = x, y
                return
        st.session_state.markers.append({"uid": str(uuid.uuid4()), "tipo": tipo, "x": x, "y": y})
    else:
        st.session_state.markers.append({"uid": str(uuid.uuid4()), "tipo": tipo, "x": x, "y": y})

# ============================================================================
# DESENHO TÁTICO
# ============================================================================

def desenhar_seta(
    imagem: Image.Image,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    cor: str,
    largura: int,
) -> Image.Image:
    """
    Desenha uma seta sobre a imagem.
    x1,y1 = início
    x2,y2 = fim
    """

    img = imagem.copy().convert("RGBA")
    draw = ImageDraw.Draw(img)

    # Linha principal
    draw.line(
        [(x1, y1), (x2, y2)],
        fill=cor,
        width=largura,
    )

    # Direção da seta
    angulo = math.atan2(y2 - y1, x2 - x1)

    tamanho_ponta = max(10, largura * 3)

    angulo1 = angulo + math.radians(150)
    angulo2 = angulo - math.radians(150)

    p1 = (
        x2 + tamanho_ponta * math.cos(angulo1),
        y2 + tamanho_ponta * math.sin(angulo1),
    )

    p2 = (
        x2 + tamanho_ponta * math.cos(angulo2),
        y2 + tamanho_ponta * math.sin(angulo2),
    )

    draw.polygon(
        [(x2, y2), p1, p2],
        fill=cor,
    )

    return img


def adicionar_seta(x1: float, y1: float, x2: float, y2: float):
    """
    Guarda uma seta no estado da aplicação.
    """

    st.session_state.desenhos.append({
        "tipo": "seta",
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "cor": st.session_state.cor_pincel,
        "largura": st.session_state.tamanho_pincel,
    })


def desenhar_setas_salvas(
    imagem: Image.Image,
    desenhos: list[dict],
) -> Image.Image:
    """
    Desenha todas as setas salvas sobre o mapa.
    """

    resultado = imagem.copy()

    for desenho in desenhos:
        if desenho.get("tipo") != "seta":
            continue

        resultado = desenhar_seta(
            resultado,
            desenho["x1"],
            desenho["y1"],
            desenho["x2"],
            desenho["y2"],
            desenho.get("cor", "#FF0000"),
            desenho.get("largura", 4),
        )

    return resultado
# ============================================================================
# BARRA LATERAL
# ============================================================================
mapas_disponiveis = [f.name for f in MAPS_DIR.iterdir() if f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.dds')]

with st.sidebar:
    st.header("⚙️ Ferramentas")

    with st.expander("🗺️ Adicionar mapa novo", expanded=not mapas_disponiveis):
        novo_mapa = st.file_uploader(
    "Imagem do mapa (.png/.jpg/.jpeg/.dds)",
    type=["png", "jpg", "jpeg", "dds"],
    key="upload_mapa"
)
        if novo_mapa is not None:
            destino = MAPS_DIR / novo_mapa.name
            destino.write_bytes(novo_mapa.getbuffer())
            st.success(f"'{novo_mapa.name}' salvo! Selecione ele na lista abaixo.")
            st.rerun()

    if not mapas_disponiveis:
        st.error("Nenhum mapa ainda — use 'Adicionar mapa novo' acima.")
        st.stop()
    mapa_selecionado = st.selectbox("Mapa", mapas_disponiveis)

    lado = st.radio("Lado da jogada", ["TR", "CT"], horizontal=True)
    tipo_round = st.selectbox("Tipo de round", ROUND_TYPES)
    nome_jogada = st.text_input("Nome da jogada", "Exec")
    modo_esboco = st.checkbox("🌑 Modo Esboço", value=True, disabled=not CV2_OK)
    if not CV2_OK:
        st.caption("opencv não instalado — filtro de esboço desativado.")
    tamanho_tela = st.slider(
        "Tamanho da tela", 300, 1200, 380, step=20,
        help="No celular, deixe perto de 380-420 pra caber sem rolar de lado.",
    )

    st.divider()
    st.subheader("🎮 Modo")
    st.session_state.modo = st.radio(
        "O que fazer ao tocar no mapa:",
        ["Posicionar", "Mover", "Apagar"],
        horizontal=True,
        index=["Posicionar", "Mover", "Apagar"].index(st.session_state.modo),
    )

    token_selecionado = None
    if st.session_state.modo == "Posicionar":
        grupo = st.radio("Time", ["CT", "TR", "Utilitário"], horizontal=True)
        if grupo == "CT":
            token_selecionado = st.radio("Qual CT?", [f"CT {i}" for i in range(1, 6)], horizontal=True)
        elif grupo == "TR":
            token_selecionado = st.radio("Qual TR?", [f"TR {i}" for i in range(1, 6)], horizontal=True)
        else:
            token_selecionado = st.radio("Qual granada?", ["Smoke", "Flash", "HE", "Molotov"], horizontal=True)
        st.caption(f"Toque no mapa pra colocar/mover **{token_selecionado}**.")
    elif st.session_state.modo == "Mover":
        if st.session_state.marcador_segurando:
            m = next((x for x in st.session_state.markers if x["uid"] == st.session_state.marcador_segurando), None)
            if m:
                st.info(f"✋ Segurando **{m['tipo']}** — toque onde quer soltar.")
                if st.button("Cancelar", use_container_width=True):
                    st.session_state.marcador_segurando = None
                    st.rerun()
        else:
            st.caption("Toque perto de um marcador pra pegar ele, depois toque de novo pra soltar.")
    else:
        st.caption("Toque perto de um marcador pra apagar ele.")

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🗑️ Limpar tudo", use_container_width=True):
            st.session_state.markers = []
            st.session_state.marcador_segurando = None
            st.rerun()
    with col_b:
        salvar_clicado = st.button("💾 Salvar", type="primary", use_container_width=True)

# ============================================================================
# TELA PRINCIPAL — TABULEIRO
# ============================================================================
abas = st.tabs(["✏️ Prancheta", "📁 Minhas Jogadas"])

with abas[0]:
    caminho_mapa = MAPS_DIR / mapa_selecionado
    try:
        fundo = get_fundo(caminho_mapa, modo_esboco)
    except Exception as e:  # noqa: BLE001
        st.error(f"Erro ao abrir {mapa_selecionado}: {e}")
        st.stop()

    imagem_com_marcadores = desenhar_marcadores(fundo, st.session_state.markers, st.session_state.marcador_segurando)

    resultado = streamlit_image_coordinates(
        imagem_com_marcadores, width=tamanho_tela, key=f"coords_{mapa_selecionado}",
    )

    if resultado is not None and resultado.get("unix_time") != st.session_state.ultimo_click_ts:
        st.session_state.ultimo_click_ts = resultado.get("unix_time")

        # converte do espaço de pixels EXIBIDO pro espaço da imagem ORIGINAL
        escala_x = fundo.width / resultado["width"]
        escala_y = fundo.height / resultado["height"]
        x_real = resultado["x"] * escala_x
        y_real = resultado["y"] * escala_y
        limiar_px = LIMIAR_PROXIMIDADE_FRAC * min(fundo.width, fundo.height)

        if st.session_state.modo == "Posicionar" and token_selecionado:
            colocar_ou_mover(token_selecionado, x_real, y_real)
            st.rerun()

        elif st.session_state.modo == "Mover":
            if st.session_state.marcador_segurando is None:
                alvo = marcador_mais_proximo(x_real, y_real, limiar_px)
                if alvo:
                    st.session_state.marcador_segurando = alvo["uid"]
                else:
                    st.toast("Nenhum marcador perto desse ponto.")
                st.rerun()
            else:
                for m in st.session_state.markers:
                    if m["uid"] == st.session_state.marcador_segurando:
                        m["x"], m["y"] = x_real, y_real
                        break
                st.session_state.marcador_segurando = None
                st.rerun()

        elif st.session_state.modo == "Apagar":
            alvo = marcador_mais_proximo(x_real, y_real, limiar_px)
            if alvo:
                st.session_state.markers = [m for m in st.session_state.markers if m["uid"] != alvo["uid"]]
                st.toast(f"{alvo['tipo']} apagado.")
            else:
                st.toast("Nenhum marcador perto desse ponto.")
            st.rerun()

    if salvar_clicado:
        timestamp_str = __import__("datetime").datetime.now().strftime("%d%m%Y_%H%M%S")
        nome_base = f"{nome_jogada.replace(' ', '_')}_{timestamp_str}"
        mapa_stem = Path(mapa_selecionado).stem
        slug_tipo = ROUND_TYPE_SLUGS[tipo_round]
        pasta_destino = JOGADAS_DIR / mapa_stem / slug_tipo
        pasta_destino.mkdir(parents=True, exist_ok=True)

        (pasta_destino / f"{nome_base}.json").write_text(
            json.dumps({
                "mapa": mapa_selecionado,
                "lado": lado,
                "tipo_round": tipo_round,
                "markers": st.session_state.markers,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        imagem_com_marcadores.save(pasta_destino / f"{nome_base}.png", "PNG")
        st.success(
            f"✅ Jogada salva em **{mapa_stem} → {tipo_round}** "
            "(editável depois — carrega de novo pra mexer)."
        )

# ============================================================================
# MINHAS JOGADAS — organizado por mapa, e dentro de cada mapa por tipo de round
# ============================================================================
with abas[1]:
    st.subheader("📁 Táticas prontas")

    mapas_com_jogadas = sorted(
        d.name for d in JOGADAS_DIR.iterdir() if d.is_dir() and any(d.rglob("*.json"))
    ) if JOGADAS_DIR.exists() else []

    if not mapas_com_jogadas:
        st.info("Nenhuma jogada salva ainda.")
    else:
        mapa_filtro = st.selectbox("Mapa", mapas_com_jogadas, key="filtro_mapa_jogadas")
        pasta_mapa = JOGADAS_DIR / mapa_filtro

        tabs_tipo = st.tabs(ROUND_TYPES)
        for tab, tipo in zip(tabs_tipo, ROUND_TYPES):
            with tab:
                pasta_tipo = pasta_mapa / ROUND_TYPE_SLUGS[tipo]
                jsons = sorted(pasta_tipo.glob("*.json")) if pasta_tipo.exists() else []

                if not jsons:
                    st.info(f"Nenhuma jogada '{tipo}' salva pra esse mapa ainda.")
                for arq_json in jsons:
                    dados_preview = json.loads(arq_json.read_text(encoding="utf-8"))
                    lado_badge = dados_preview.get("lado", "?")
                    with st.expander(f"{arq_json.stem}  ·  lado {lado_badge}"):
                        png_path = arq_json.with_suffix(".png")
                        if png_path.exists():
                            st.image(str(png_path), use_column_width=True)
                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("🔄 Carregar pra editar", key=f"load_{arq_json}", use_container_width=True):
                                dados = json.loads(arq_json.read_text(encoding="utf-8"))
                                if dados["mapa"] in mapas_disponiveis:
                                    st.session_state.markers = dados["markers"]
                                    st.session_state.marcador_segurando = None
                                    st.success(f"Carregado! Vá na aba Prancheta (mapa: {dados['mapa']}).")
                                else:
                                    st.error(f"O mapa '{dados['mapa']}' dessa jogada não está mais na pasta maps/.")
                        with c2:
                            if st.button("🗑️ Excluir", key=f"del_{arq_json}", use_container_width=True):
                                arq_json.unlink(missing_ok=True)
                                png_path.unlink(missing_ok=True)
                                st.rerun()