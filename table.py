# -*- coding: utf-8 -*-
"""
Prancheta Tática CS2 — versão 2 com Banco de Dados PostgreSQL (Supabase)
"""
from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import text  # IMPORTAÇÃO ADICIONADA AQUI

try:
    import imageio.v3 as iio
    IMAGEIO_OK = True
except ImportError:
    IMAGEIO_OK = False

import streamlit as st
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
MAPS_DIR.mkdir(parents=True, exist_ok=True)

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
# CONEXÃO COM O BANCO DE DADOS (SUPABASE / POSTGRES)
# ============================================================================
try:
    conn = st.connection("postgres", type="sql", autocommit=True, pool_pre_ping=True, pool_recycle=300)
except Exception:
    conn = None

# ============================================================================
# TOKENS
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
LIMIAR_PROXIMIDADE_FRAC = 0.045

ROUND_TYPES = ["Eco", "Forçado", "Comprado"]
ROUND_TYPE_SLUGS = {"Eco": "eco", "Forçado": "forcado", "Comprado": "comprado"}


def font(size: int):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except Exception:
        return ImageFont.load_default()


# ============================================================================
# ESTADO
# ============================================================================
if "markers" not in st.session_state:
    st.session_state.markers = []
if "modo" not in st.session_state:
    st.session_state.modo = "Posicionar"
if "marcador_segurando" not in st.session_state:
    st.session_state.marcador_segurando = None
if "ultimo_click_ts" not in st.session_state:
    st.session_state.ultimo_click_ts = None
if "fundo_cache" not in st.session_state:
    st.session_state.fundo_cache = {}
if "desenhos" not in st.session_state:
    st.session_state.desenhos = []
if "cor_pincel" not in st.session_state:
    st.session_state.cor_pincel = "#FF0000"
if "tamanho_pincel" not in st.session_state:
    st.session_state.tamanho_pincel = 4
if "ponto_seta" not in st.session_state:
    st.session_state.ponto_seta = None
if "desenhos_livres" not in st.session_state:
    st.session_state.desenhos_livres = []

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


@st.cache_data
def get_fundo(caminho_mapa_str: str, modo_esboco: bool) -> Image.Image:
    caminho_mapa = Path(caminho_mapa_str)
    extensao = caminho_mapa.suffix.lower()

    if extensao == ".dds":
        if not IMAGEIO_OK:
            raise RuntimeError("Para abrir mapas DDS, instale o pacote imageio")
        img_array = iio.imread(caminho_mapa)
        img = Image.fromarray(img_array).convert("RGB")
    else:
        img = Image.open(caminho_mapa).convert("RGB")

    if modo_esboco:
        img = aplicar_filtro_esboco(img)

    return img


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


def desenhar_seta(
    imagem: Image.Image,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    cor: str,
    largura: int,
) -> Image.Image:
    img = imagem.copy().convert("RGBA")
    draw = ImageDraw.Draw(img)
    draw.line([(x1, y1), (x2, y2)], fill=cor, width=largura)
    angulo = math.atan2(y2 - y1, x2 - x1)
    tamanho_ponta = max(10, largura * 3)
    angulo1 = angulo + math.radians(150)
    angulo2 = angulo - math.radians(150)
    p1 = (x2 + tamanho_ponta * math.cos(angulo1), y2 + tamanho_ponta * math.sin(angulo1))
    p2 = (x2 + tamanho_ponta * math.cos(angulo2), y2 + tamanho_ponta * math.sin(angulo2))
    draw.polygon([(x2, y2), p1, p2], fill=cor)
    return img


def adicionar_seta(x1: float, y1: float, x2: float, y2: float):
    st.session_state.desenhos.append({
        "tipo": "seta",
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "cor": st.session_state.cor_pincel,
        "largura": st.session_state.tamanho_pincel,
    })


def desenhar_setas_salvas(imagem: Image.Image, desenhos: list[dict]) -> Image.Image:
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
    MODOS = ["Posicionar", "Mover", "Apagar", "Desenhar", "Seta"]
    st.session_state.modo = st.radio(
        "O que fazer ao tocar no mapa:",
        MODOS,
        horizontal=True,
        index=MODOS.index(st.session_state.modo),
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
    elif st.session_state.modo == "Apagar":
        st.caption("Toque perto de um marcador pra apagar ele.")
    elif st.session_state.modo == "Desenhar":
        st.session_state.cor_pincel = st.color_picker(
            "🎨 Cor do pincel",
            value=st.session_state.cor_pincel,
            key="color_picker_desenho",
        )
        st.session_state.tamanho_pincel = st.slider(
            "📏 Espessura",
            min_value=1, max_value=20,
            value=st.session_state.tamanho_pincel,
            step=1, key="slider_tamanho_desenho",
        )
        st.caption("Desenhe livremente sobre o mapa.")
        if st.button("🧹 Limpar desenhos", use_container_width=True):
            st.session_state.desenhos = []
            st.rerun()
    elif st.session_state.modo == "Seta":
        st.session_state.cor_pincel = st.color_picker(
            "🎨 Cor da seta",
            value=st.session_state.cor_pincel,
            key="color_picker_seta",
        )
        st.session_state.tamanho_pincel = st.slider(
            "📏 Espessura da seta",
            min_value=1, max_value=20,
            value=st.session_state.tamanho_pincel,
            step=1, key="slider_tamanho_seta",
        )
        if st.session_state.ponto_seta is None:
            st.caption("Toque no ponto inicial da seta.")
        else:
            st.info("Agora toque no ponto final da seta.")
        if st.button("↩️ Cancelar seta", use_container_width=True):
            st.session_state.ponto_seta = None
            st.rerun()
        if st.button("🧹 Limpar setas", use_container_width=True):
            st.session_state.desenhos = [d for d in st.session_state.desenhos if d.get("tipo") != "seta"]
            st.session_state.ponto_seta = None
            st.rerun()

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🗑️ Limpar tudo", use_container_width=True):
            st.session_state.markers = []
            st.session_state.desenhos = []
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
        fundo = get_fundo(str(caminho_mapa), modo_esboco)
    except Exception as e:
        st.error(f"Erro ao abrir {mapa_selecionado}: {e}")
        st.stop()

    imagem_com_marcadores = desenhar_marcadores(
        fundo,
        st.session_state.markers,
        st.session_state.marcador_segurando,
    )
    imagem_com_marcadores = desenhar_setas_salvas(
        imagem_com_marcadores,
        st.session_state.desenhos,
    )

    if st.session_state.modo == "Desenhar":
        proporcao = imagem_com_marcadores.height / imagem_com_marcadores.width
        altura_canvas = int(tamanho_tela * proporcao)

        canvas_result = st.empty()
        # Nota: se usar o st_canvas, certifique-se de importar st_canvas
        from streamlit_drawable_canvas import st_canvas
        canvas_res = st_canvas(
            fill_color="rgba(0, 0, 0, 0)",
            stroke_width=st.session_state.tamanho_pincel,
            stroke_color=st.session_state.cor_pincel,
            background_image=imagem_com_marcadores,
            update_streamlit=True,
            height=altura_canvas,
            width=tamanho_tela,
            drawing_mode="freedraw",
            key=f"canvas_desenho_{mapa_selecionado}",
        )

        if canvas_res.json_data is not None:
            objetos = canvas_res.json_data.get("objects", [])
            desenhos_livres = []
            for objeto in objetos:
                if objeto.get("type") != "path":
                    continue
                desenhos_livres.append({"tipo": "livre", "objeto": objeto})
            st.session_state.desenhos_livres = desenhos_livres
    else:
        resultado = streamlit_image_coordinates(
            imagem_com_marcadores,
            width=tamanho_tela,
            key=f"coords_{mapa_selecionado}",
        )

        if resultado is not None and resultado.get("unix_time") != st.session_state.ultimo_click_ts:
            st.session_state.ultimo_click_ts = resultado.get("unix_time")

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

            elif st.session_state.modo == "Seta":
                if st.session_state.ponto_seta is None:
                    st.session_state.ponto_seta = (x_real, y_real)
                    st.toast("📍 Ponto inicial definido.")
                else:
                    x1, y1 = st.session_state.ponto_seta
                    adicionar_seta(x1, y1, x_real, y_real)
                    st.session_state.ponto_seta = None
                    st.toast("➡️ Seta criada.")
                st.rerun()

    if salvar_clicado:
        if conn is None:
            st.error("Conexão com o banco de dados PostgreSQL não foi configurada nos secrets do Streamlit.")
        else:
            try:
                with conn.session as s:
                    s.execute(
                        text("""
                        INSERT INTO jogadas (nome_jogada, mapa, lado, tipo_round, markers, desenhos, desenhos_livres)
                        VALUES (:nome, :mapa, :lado, :tipo_round, CAST(:markers AS jsonb), CAST(:desenhos AS jsonb), CAST(:desenhos_livres AS jsonb))
                        """),
                        {
                            "nome": nome_jogada,
                            "mapa": mapa_selecionado,
                            "lado": lado,
                            "tipo_round": tipo_round,
                            "markers": json.dumps(st.session_state.markers),
                            "desenhos": json.dumps(st.session_state.desenhos),
                            "desenhos_livres": json.dumps(st.session_state.get("desenhos_livres", [])),
                        }
                    )
                    s.commit()
                st.success(f"✅ Jogada '{nome_jogada}' salva com sucesso no banco de dados da equipa!")
            except Exception as ex:
                st.error(f"Erro ao salvar no banco de dados: {ex}")

# ============================================================================
# MINHAS JOGADAS — VIA BANCO SQL (POSTGRESQL)
# ============================================================================
with abas[1]:
    st.subheader("📁 Táticas da Equipa (Nuvem)")

    if conn is None:
        st.warning("⚠️ Conexão com o banco de dados não configurada. Configure os Secrets no Streamlit Cloud.")
    else:
        try:
            df_jogadas = conn.query("SELECT * FROM jogadas ORDER BY criado_em DESC;", ttl=0)
            
            if df_jogadas.empty:
                st.info("Nenhuma jogada salva na nuvem ainda.")
            else:
                mapas_no_banco = sorted(df_jogadas["mapa"].unique().tolist())
                mapa_filtro = st.selectbox("Filtrar por Mapa", mapas_no_banco, key="filtro_mapa_jogadas")
                
                df_filtrado = df_jogadas[df_jogadas["mapa"] == mapa_filtro]

                tabs_tipo = st.tabs(ROUND_TYPES)
                for tab, tipo in zip(tabs_tipo, ROUND_TYPES):
                    with tab:
                        df_tipo = df_filtrado[df_filtrado["tipo_round"] == tipo]
                        
                        if df_tipo.empty:
                            st.info(f"Nenhuma jogada '{tipo}' salva para este mapa.")
                        else:
                            for idx, row in df_tipo.iterrows():
                                jogada_id = row["id"]
                                nome_j = row["nome_jogada"]
                                lado_j = row["lado"]
                                
                                with st.expander(f"{nome_j}  ·  Lado {lado_j}  ·  ID: {jogada_id}"):
                                    m_data = row["markers"]
                                    d_data = row["desenhos"]
                                    dl_data = row["desenhos_livres"]
                                    
                                    markers_preview = json.loads(m_data) if isinstance(m_data, str) else m_data
                                    desenhos_preview = json.loads(d_data) if isinstance(d_data, str) else (d_data if d_data else [])
                                    dl_preview = json.loads(dl_data) if isinstance(dl_data, str) else (dl_data if dl_data else [])
                                    
                                    caminho_mapa_preview = MAPS_DIR / row["mapa"]
                                    if caminho_mapa_preview.exists():
                                        try:
                                            # Reconstrói a imagem da tática dinamicamente
                                            fundo_preview = get_fundo(str(caminho_mapa_preview), modo_esboco)
                                            img_preview = desenhar_marcadores(fundo_preview, markers_preview, None)
                                            img_preview = desenhar_setas_salvas(img_preview, desenhos_preview)
                                            
                                            st.image(img_preview, use_container_width=True)
                                            
                                            # Permite baixar o PNG gerado
                                            import io
                                            buf = io.BytesIO()
                                            img_preview.save(buf, format="PNG")
                                            st.download_button(
                                                "⬇️ Baixar PNG",
                                                data=buf.getvalue(),
                                                file_name=f"{nome_j}_{tipo}.png",
                                                mime="image/png",
                                                key=f"dl_sql_{jogada_id}",
                                                use_container_width=True
                                            )
                                        except Exception as e:
                                            st.error(f"Erro ao gerar pré-visualização: {e}")
                                    else:
                                        st.warning("Mapa não encontrado para gerar pré-visualização.")

                                    c1, c2 = st.columns(2)
                                    with c1:
                                        if st.button("🔄 Carregar pra editar", key=f"load_sql_{jogada_id}", use_container_width=True):
                                            st.session_state.markers = markers_preview
                                            st.session_state.desenhos = desenhos_preview
                                            st.session_state.desenhos_livres = dl_preview
                                            st.session_state.marcador_segurando = None
                                            st.success("Jogada carregada! Vá para a aba Prancheta.")
                                    with c2:
                                        if st.button("🗑️ Excluir da nuvem", key=f"del_sql_{jogada_id}", use_container_width=True):
                                            try:
                                                with conn.session as s:
                                                    s.execute(text("DELETE FROM jogadas WHERE id = :id"), {"id": jogada_id})
                                                    s.commit()
                                                st.success("Jogada excluída com sucesso!")
                                                st.rerun()
                                            except Exception as exc:
                                                st.error(f"Erro ao excluir: {exc}")
        except Exception as e:
            st.error(f"Erro ao consultar o banco de dados: {e}. Verifique se a tabela 'jogadas' foi criada corretamente.")
