import array
import io
import math
import os
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox

from googletrans import Translator

# Bibliotecas opcionais: se faltarem, o programa abre e avisa ao usar a função
try:
    import speech_recognition as sr
    import sounddevice as sd
except (ImportError, OSError):  # OSError: PortAudio não encontrado
    sr = None
    sd = None

try:
    from gtts import gTTS
except ImportError:
    gTTS = None

TAXA = 16000  # taxa de amostragem da gravação (Hz)


# =====================================================================
#  ÁUDIO: gravar a voz e tocar a tradução
# =====================================================================
def gravar_voz(parar=None, timeout=6, limite=30, silencio=1.2):
    """Grava do microfone e devolve um sr.AudioData.

    - Espera até `timeout` s pelo início da fala.
    - Pára após `silencio` s de silêncio, `limite` s no total, ou quando
      o evento `parar` é activado (utilizador tocou para parar).
    """
    bloco = int(TAXA * 0.1)  # blocos de 0,1 s

    def volume(dados):
        amostras = array.array("h")
        amostras.frombytes(dados)
        if not amostras:
            return 0
        return math.sqrt(sum(x * x for x in amostras) / len(amostras))

    with sd.RawInputStream(samplerate=TAXA, channels=1, dtype="int16", blocksize=bloco) as fluxo:

        def ler():
            dados, _ = fluxo.read(bloco)
            return bytes(dados)

        # 1) calibrar o ruído ambiente (~0,6 s)
        ambiente = [volume(ler()) for _ in range(6)]
        limiar = max(sum(ambiente) / len(ambiente) * 2.5, 300)

        # 2) esperar a fala e gravar até haver silêncio
        anteriores, gravado = [], []
        falando = False
        espera, silenciosos = 0.0, 0
        while True:
            dados = ler()
            if parar is not None and parar.is_set():
                if falando:
                    break
                raise TimeoutError("Cancelado")
            v = volume(dados)
            if not falando:
                anteriores = (anteriores + [dados])[-3:]  # não cortar a 1.ª sílaba
                if v > limiar:
                    falando = True
                    gravado = list(anteriores)
                else:
                    espera += 0.1
                    if espera >= timeout:
                        raise TimeoutError("Sem fala detectada")
            else:
                gravado.append(dados)
                silenciosos = silenciosos + 1 if v < limiar else 0
                if silenciosos * 0.1 >= silencio or len(gravado) * 0.1 >= limite:
                    break

    return sr.AudioData(b"".join(gravado), TAXA, 2)


def tocar_mp3(dados):
    """Reproduz bytes MP3. No Windows usa o MCI do sistema (não instala nada)."""
    if os.name == "nt":
        import ctypes

        caminho = os.path.join(tempfile.gettempdir(), "tradutor_voz.mp3")
        with open(caminho, "wb") as f:
            f.write(dados)
        mci = ctypes.windll.winmm.mciSendStringW
        mci("close voz", None, 0, 0)
        erro = mci(f'open "{caminho}" type mpegvideo alias voz', None, 0, 0)
        if erro:
            raise RuntimeError(f"Não foi possível abrir o áudio (MCI {erro})")
        mci("play voz wait", None, 0, 0)  # 'wait' bloqueia até acabar
        mci("close voz", None, 0, 0)
    else:
        import pygame  # fora do Windows: pip install pygame

        pygame.mixer.init()
        pygame.mixer.music.load(io.BytesIO(dados), "mp3")
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(100)


BG = "#1e1e2e"
BG_CARD = "#2a2a3c"
BG_TEXT = "#313244"
FG = "#cdd6f4"
FG_MUTED = "#9399b2"
ACCENT = "#89b4fa"
DANGER = "#f38ba8"
VERDE = "#a6e3a1"
FONT = ("Segoe UI", 11)

IDIOMAS = {
    "pt": {"nome": "Português", "voz": "pt-PT", "cor": ACCENT, "fundo": "#1d2236"},
    "en": {"nome": "English", "voz": "en-US", "cor": VERDE, "fundo": "#1c2b26"},
}
OUTRO = {"pt": "en", "en": "pt"}

tradutor = Translator()


class MicBotao(tk.Canvas):
    def __init__(self, pai, nome, cor, fundo, comando):
        super().__init__(pai, bg=fundo, highlightthickness=0, cursor="hand2")
        self.nome, self.cor, self.comando = nome, cor, comando
        self.estado = "repouso"  # repouso | gravando | ocupado
        self._fase = 0.0
        self._animando = False
        self._cx = self._cy = 0
        self._r = 50
        self._anel = None

        self.bind("<Configure>", lambda e: self._desenhar())
        self.bind("<Button-1>", lambda e: self.comando())  # toda a área é clicável

    def definir_estado(self, estado):
        self.estado = estado
        self.configure(cursor="arrow" if estado == "ocupado" else "hand2")
        self._desenhar()
        if estado == "gravando" and not self._animando:
            self._animando = True
            self._animar()

    def _desenhar(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20 or h < 20:
            return
        self.delete("all")

        cx, cy = w / 2, h * 0.42
        r = max(40, min(w * 0.34, h * 0.30))
        self._cx, self._cy, self._r = cx, cy, r

        if self.estado == "gravando":
            fundo, icone, dica = DANGER, "#1e1e2e", "A ouvir…  toque para parar"
        elif self.estado == "ocupado":
            fundo, icone, dica = BG_TEXT, FG_MUTED, "Aguarde…"
        else:
            fundo, icone, dica = self.cor, "#1e1e2e", "Toque e fale"

        self._anel = self.create_oval(
            cx - r - 8, cy - r - 8, cx + r + 8, cy + r + 8,
            outline=DANGER, width=4,
            state="normal" if self.estado == "gravando" else "hidden",
        )
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fundo, outline="")
        # tamanhos negativos = pixels (escalam com o círculo)
        self.create_text(cx, cy, text="🎤", font=("Segoe UI Emoji", -int(r * 0.95)), fill=icone)

        tam = max(14, int(r * 0.30))
        y_nome = cy + r + r * 0.42
        self.create_text(cx, y_nome, text=self.nome, font=("Segoe UI", -tam, "bold"), fill=FG)
        self.create_text(cx, y_nome + tam * 1.6, text=dica,
                         font=("Segoe UI", -max(11, int(tam * 0.6))), fill=FG_MUTED)

    def _animar(self):
        if self.estado != "gravando":
            self._animando = False
            return
        self._fase += 0.3
        r = self._r + 8 + 8 * math.sin(self._fase)
        if self._anel is not None:
            self.coords(self._anel, self._cx - r, self._cy - r, self._cx + r, self._cy + r)
        self.after(60, self._animar)


# =====================================================================
#  APLICAÇÃO
# =====================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Tradutor de Voz  PT ⇄ EN")
        self.geometry("900x620")
        self.minsize(560, 420)
        self.configure(bg=BG)

        self.estado = "repouso"  # repouso | gravando | processando
        self.lado_ativo = None
        self.parar_evt = threading.Event()
        self.historico = []  # [(lado, original, traducao), ...]
        self.janela_conversa = None
        self.log = None
        self._contador = 0

        self.columnconfigure(0, weight=1, uniform="mic")
        self.columnconfigure(1, weight=1, uniform="mic")
        self.rowconfigure(1, weight=1)

        self._criar_barra_topo()
        self._criar_microfones()
        self._criar_rodape()

    # ---------------- interface ----------------
    def _criar_barra_topo(self):
        barra = tk.Frame(self, bg=BG)
        barra.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=10)
        barra.columnconfigure(0, weight=1)
        tk.Label(barra, text="Tradutor de Voz", font=("Segoe UI", 15, "bold"),
                 bg=BG, fg=FG).grid(row=0, column=0, sticky="w")
        tk.Button(barra, text="  Ver conversa", command=self.ver_conversa,
                  font=("Segoe UI", 10), bg=BG_CARD, fg=FG, activebackground=BG_TEXT,
                  activeforeground=FG, relief="flat", cursor="hand2",
                  padx=14, pady=6, bd=0).grid(row=0, column=1)

    def _criar_microfones(self):
        self.mic = {}
        for coluna, lado in enumerate(("pt", "en")):
            cfg = IDIOMAS[lado]
            botao = MicBotao(self, cfg["nome"], cfg["cor"], cfg["fundo"],
                             lambda l=lado: self.alternar_gravacao(l))
            botao.grid(row=1, column=coluna, sticky="nsew", padx=(16, 4) if coluna == 0 else (4, 16))
            self.mic[lado] = botao

    def _criar_rodape(self):
        self.status = tk.Label(self, text="Toque no microfone do seu idioma e fale",
                               font=("Segoe UI", 10), bg=BG_CARD, fg=FG_MUTED,
                               anchor="center", pady=8)
        self.status.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    # ---------------- estado ----------------
    def _status(self, texto):
        """Seguro para chamar de qualquer thread."""
        self.after(0, self.status.configure, {"text": texto})

    def _definir_estado(self, estado, lado=None):
        self.estado = estado
        for l, botao in self.mic.items():
            if estado == "repouso":
                botao.definir_estado("repouso")
            elif estado == "gravando":
                botao.definir_estado("gravando" if l == lado else "ocupado")
            else:
                botao.definir_estado("ocupado")

    def _reset(self, mensagem="Pronto  •  toque num microfone para falar"):
        self._definir_estado("repouso")
        self.lado_ativo = None
        self.status.configure(text=mensagem)

    # ---------------- gravação ----------------
    def alternar_gravacao(self, lado):
        if self.estado == "gravando":
            if self.lado_ativo == lado:  # segundo toque = parar
                self.parar_evt.set()
                self._status("A processar…")
            return
        if self.estado != "repouso":
            return
        if sr is None or sd is None:
            messagebox.showerror("Biblioteca em falta",
                                 "Instale com:\npip install SpeechRecognition sounddevice")
            return

        self.lado_ativo = lado
        self.parar_evt.clear()
        self._definir_estado("gravando", lado)
        self.status.configure(text="A ouvir… fale agora")
        threading.Thread(target=self._worker_voz, args=(lado,), daemon=True).start()

    def _worker_voz(self, lado):
        reconhecedor = sr.Recognizer()
        try:
            audio = gravar_voz(parar=self.parar_evt)
            self.after(0, self._definir_estado, "processando")
            self._status("A reconhecer a voz…")
            texto = reconhecedor.recognize_google(audio, language=IDIOMAS[lado]["voz"])
        except TimeoutError:
            self.after(0, self._reset, "Não ouvi nada. Tente de novo.")
            return
        except sr.UnknownValueError:
            self.after(0, self._reset, "Não consegui perceber o que foi dito.")
            return
        except sr.RequestError as e:
            self.after(0, self._reset, f"Erro no serviço de voz (sem internet?): {e}")
            return
        except Exception as e:
            self.after(0, self._reset, f"Microfone indisponível ou erro: {e}")
            return

        self._traduzir_e_falar(lado, texto)

    # ---------------- tradução + voz (corre numa thread) ----------------
    def _traduzir_e_falar(self, lado, texto):
        destino = OUTRO[lado]
        try:
            self._status("A traduzir…")
            traducao = tradutor.translate(texto, src=lado, dest=destino).text
        except Exception as e:
            self.after(0, self._reset, f"Erro na tradução: {e}")
            return

        self.after(0, self._guardar_mensagem, lado, texto, traducao)
        self._falar_bloqueante(traducao, destino)
        self.after(0, self._reset)

    def _falar_bloqueante(self, texto, idioma):
        if gTTS is None:
            self._status("Para ouvir a tradução instale: pip install gTTS")
            return
        try:
            self._status(" A reproduzir a tradução…")
            memoria = io.BytesIO()
            gTTS(text=texto, lang=idioma).write_to_fp(memoria)
            tocar_mp3(memoria.getvalue())
        except Exception as e:
            self._status(f"Erro no áudio: {e}")

    def _repetir_audio(self, texto, idioma):
        """Toque no 🔊 de uma mensagem da conversa: voltar a ouvir a tradução."""
        if self.estado != "repouso":
            return
        self._definir_estado("processando")

        def tarefa():
            self._falar_bloqueante(texto, idioma)
            self.after(0, self._reset)

        threading.Thread(target=tarefa, daemon=True).start()

    # ---------------- conversa (opcional) ----------------
    def _guardar_mensagem(self, lado, original, traducao):
        self.historico.append((lado, original, traducao))
        if self.log is not None:  # janela da conversa aberta: actualiza em directo
            self._escrever_mensagem(lado, original, traducao)

    def ver_conversa(self):
        if self.janela_conversa is not None and self.janela_conversa.winfo_exists():
            self.janela_conversa.lift()
            self.janela_conversa.focus_force()
            return

        win = tk.Toplevel(self)
        win.title("Conversa")
        win.geometry("560x640")
        win.configure(bg=BG)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)
        self.janela_conversa = win

        topo = tk.Frame(win, bg=BG)
        topo.grid(row=0, column=0, sticky="ew", padx=14, pady=10)
        topo.columnconfigure(0, weight=1)
        tk.Label(topo, text="Conversa", font=("Segoe UI", 14, "bold"),
                 bg=BG, fg=FG).grid(row=0, column=0, sticky="w")
        tk.Button(topo, text="  Limpar", command=self.limpar_conversa,
                  font=("Segoe UI", 10), bg=BG_CARD, fg=FG, activebackground=BG_TEXT,
                  activeforeground=FG, relief="flat", cursor="hand2",
                  padx=12, pady=4, bd=0).grid(row=0, column=1)

        moldura = tk.Frame(win, bg=BG_CARD, padx=2, pady=2)
        moldura.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        moldura.columnconfigure(0, weight=1)
        moldura.rowconfigure(0, weight=1)

        self.log = tk.Text(moldura, wrap="word", bg=BG_CARD, fg=FG, relief="flat",
                           padx=14, pady=12, state="disabled", cursor="arrow", font=FONT)
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = tk.Scrollbar(moldura, command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

        # Estilos: português à esquerda, inglês à direita
        for lado, cfg in IDIOMAS.items():
            esq = lado == "pt"
            m_e, m_d = (8, 90) if esq else (90, 8)
            base = dict(justify="left" if esq else "right",
                        lmargin1=m_e, lmargin2=m_e, rmargin=m_d)
            self.log.tag_configure(f"{lado}_nome", foreground=cfg["cor"],
                                   font=("Segoe UI", 9, "bold"), spacing1=12, **base)
            self.log.tag_configure(f"{lado}_orig", foreground=FG_MUTED,
                                   font=("Segoe UI", 10), **base)
            self.log.tag_configure(f"{lado}_trad", foreground=FG,
                                   font=("Segoe UI", 13, "bold"), **base)
        self.log.tag_configure("dica", foreground=FG_MUTED, font=("Segoe UI", 11),
                               justify="center", spacing1=60)

        win.protocol("WM_DELETE_WINDOW", self._fechar_conversa)
        self._redesenhar_conversa()

    def _fechar_conversa(self):
        self.log = None
        if self.janela_conversa is not None:
            self.janela_conversa.destroy()
        self.janela_conversa = None

    def _redesenhar_conversa(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        if not self.historico:
            self.log.configure(state="normal")
            self.log.insert("end", "Ainda não há conversa.\nFale num dos microfones.", "dica")
            self.log.configure(state="disabled")
            return
        for lado, original, traducao in self.historico:
            self._escrever_mensagem(lado, original, traducao)

    def _escrever_mensagem(self, lado, original, traducao):
        destino = OUTRO[lado]
        self.log.configure(state="normal")
        if not self.historico[:-1] and self.log.tag_ranges("dica"):
            self.log.delete("1.0", "end")  # remove a dica "Ainda não há conversa"

        self._contador += 1
        tag_play = f"play{self._contador}"
        self.log.tag_configure(tag_play, foreground=IDIOMAS[lado]["cor"])
        self.log.tag_bind(tag_play, "<Button-1>",
                          lambda e, t=traducao, d=destino: self._repetir_audio(t, d))
        self.log.tag_bind(tag_play, "<Enter>", lambda e: self.log.configure(cursor="hand2"))
        self.log.tag_bind(tag_play, "<Leave>", lambda e: self.log.configure(cursor="arrow"))

        self.log.insert("end", f"{IDIOMAS[lado]['nome']}\n", f"{lado}_nome")
        self.log.insert("end", original + "\n", f"{lado}_orig")
        self.log.insert("end", traducao, f"{lado}_trad")
        self.log.insert("end", "  🔊\n", (f"{lado}_trad", tag_play))
        self.log.configure(state="disabled")
        self.log.see("end")

    def limpar_conversa(self):
        self.historico.clear()
        if self.log is not None:
            self._redesenhar_conversa()

if __name__ == "__main__":
    App().mainloop()