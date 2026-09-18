# 🗺️ Prancheta Tática CS2 (CS2 Tactical Board)

Uma aplicação interativa desenvolvida em **Streamlit** para criar, editar, desenhar e compartilhar táticas e estratégias de Counter-Strike 2 em equipe de forma simples e responsiva (ótimo tanto para desktop quanto para dispositivos móveis).

---

## ✨ Funcionalidades

* **Modos de Interação na Prancheta:**
  * **Posicionar:** Posicione e mova os jogadores de cada time (`CT 1-5`, `TR 1-5`) e utilitários (`Smoke`, `Flash`, `HE`, `Molotov`).
  * **Mover:** Toque em um marcador para "segurá-lo" e reposicioná-lo facilmente no tabuleiro.
  * **Apagar:** Remova marcadores rapidamente com um toque.
  * **Desenhar:** Desenhe linhas livres à mão livre com seletores de cor e espessura.
  * **Seta:** Crie setas direcionais táticas precisas definindo ponto inicial e final.
* **Filtro de Esboço (Modo Esboço):** Conversão automática do mapa em estilo tático usando processamento de imagem (`OpenCV`).
* **Sincronização em Nuvem (Supabase / PostgreSQL):** As táticas salvas ficam disponíveis centralizadas no banco de dados para todo o time acessar em tempo real por meio do Streamlit Cloud.
* **Gerenciamento de Mapas:** Suporte a arquivos de imagem `.png`, `.jpg`, `.jpeg` e até formatos texturados como `.dds`.

---

## 🛠️ Tecnologias Utilizadas

* **Python**
* **Streamlit** (Interface Web e reatividade)
* **Streamlit Image Coordinates & Drawable Canvas** (Interações espaciais no mapa)
* **OpenCV & NumPy & Pillow (PIL)** (Processamento e manipulação de imagem/filtros)
* **Supabase / PostgreSQL** (Banco de dados relacional na nuvem)

---

## 🚀 Como Executar o Projeto Localmente

1. **Clone o repositório ou baixe os arquivos:**
   ```bash
   git clone [https://github.com/seu-usuario/seu-repositorio.git](https://github.com/seu-usuario/seu-repositorio.git)
   cd seu-repositorio
