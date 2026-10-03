import array
import io
import math
import os
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox

from googletrans import Translator

# Bibliotecas opcionais: se faltarem, o resto do programa continua a funcionar
try:
    import speech_recognition as sr
    import sounddevice as sd
except ImportError:
    sr = None
    sd = None

try:
    from gtts import gTTS
except ImportError:
    gTTS = None

TAXA = 16000  # taxa de amostragem da gravação (Hz)


def gravar_voz(timeout=6, limite=20, silencio=1.0):
    """Grava do microfone (sounddevice) e devolve um sr.AudioData.

    Espera até `timeout` s pelo início da fala, grava até haver `silencio` s de
    silêncio ou até `limite` s no total.
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

        # 2) esperar o início da fala (guarda os últimos blocos para não cortar a 1.ª sílaba)
        anteriores = []
        gravado = []
        falando = False
        espera = 0.0
        silenciosos = 0
        while True:
            dados = ler()
            v = volume(dados)
            if not falando:
                anteriores = (anteriores + [dados])[-3:]
                if v > limiar:
                    falando = True
                    gravado = anteriores + []
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
        mci("play voz wait", None, 0, 0)  # 'wait' bloqueia até acabar (estamos numa thread)
        mci("close voz", None, 0, 0)
    else:
        import pygame  # fora do Windows: pip install pygame

        pygame.mixer.init()
        pygame.mixer.music.load(io.BytesIO(dados), "mp3")
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(100)


# ---------- Configuração ----------
BG = "#1e1e2e"
BG_CARD = "#2a2a3c"
BG_TEXT = "#313244"
FG = "#cdd6f4"
FG_MUTED = "#9399b2"
ACCENT = "#89b4fa"
ACCENT_HOVER = "#b4befe"
DANGER = "#f38ba8"
FONT = ("Segoe UI", 11)
FONT_TITLE = ("Segoe UI", 18, "bold")

# código googletrans -> (nome, código do reconhecimento de voz)
IDIOMAS = {
    "pt": ("Português", "pt-PT"),
    "en": ("Inglês", "en-US"),
}

tradutor = Translator()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Tradutor PT ⇄ EN")
        self.geometry("760x680")
        self.minsize(600, 600)
        self.configure(bg=BG)

        self.origem = "pt"
        self.destino = "en"
        self.gravando = False
        self._fase = 0.0

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self._criar_cabecalho()
        self._criar_barra_idiomas()
        self._criar_corpo()
        self._criar_rodape()
        self._criar_indicador_microfone()
        self.atualizar_rotulos()

        self.entrada.focus_set()
        self.bind("<Control-Return>", lambda e: self.traduzir())

    # ================= INTERFACE =================
    def _criar_cabecalho(self):
        frame = tk.Frame(self, bg=BG)
        frame.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 5))
        tk.Label(frame, text="Tradutor", font=FONT_TITLE, bg=BG, fg=ACCENT).grid(
            row=0, column=0, sticky="w"
        )

    def _criar_barra_idiomas(self):
        barra = tk.Frame(self, bg=BG_CARD)
        barra.grid(row=1, column=0, sticky="ew", padx=20, pady=10)
        barra.columnconfigure(0, weight=1, uniform="lang")
        barra.columnconfigure(2, weight=1, uniform="lang")

        self.lbl_origem = tk.Label(barra, font=("Segoe UI", 13, "bold"), bg=BG_CARD, fg=FG)
        self.lbl_origem.grid(row=0, column=0, pady=12)

        self.btn_trocar = self._botao(barra, "⇄", self.trocar_idiomas, primario=True)
        self.btn_trocar.configure(font=("Segoe UI", 14, "bold"), padx=14, pady=2)
        self.btn_trocar.grid(row=0, column=1, padx=10)

        self.lbl_destino = tk.Label(barra, font=("Segoe UI", 13, "bold"), bg=BG_CARD, fg=FG)
        self.lbl_destino.grid(row=0, column=2, pady=12)

    def _criar_corpo(self):
        corpo = tk.Frame(self, bg=BG)
        corpo.grid(row=2, column=0, sticky="nsew", padx=20)
        corpo.columnconfigure(0, weight=1)
        corpo.rowconfigure(1, weight=1)
        corpo.rowconfigure(4, weight=1)

        # --- Entrada: título + botão ouvir ---
        topo_in = tk.Frame(corpo, bg=BG)
        topo_in.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        topo_in.columnconfigure(0, weight=1)
        self.lbl_titulo_in = tk.Label(topo_in, font=FONT, bg=BG, fg=FG)
        self.lbl_titulo_in.grid(row=0, column=0, sticky="w")
        self._botao_pequeno(topo_in, "🔊 Ouvir", self.ouvir_original).grid(row=0, column=1)

        self.entrada = self._caixa_texto(corpo, row=1, estado="normal")

        # --- Botões principais ---
        botoes = tk.Frame(corpo, bg=BG)
        botoes.grid(row=2, column=0, sticky="ew", pady=12)
        botoes.columnconfigure(0, weight=1)

        self.btn_traduzir = self._botao(botoes, "Traduzir", self.traduzir, primario=True)
        self.btn_traduzir.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.btn_mic = self._botao(botoes, "🎤 Falar", self.iniciar_gravacao)
        self.btn_mic.grid(row=0, column=1, padx=(0, 8))
        self._botao(botoes, "Limpar", self.limpar).grid(row=0, column=2, padx=(0, 8))
        self._botao(botoes, "Copiar", self.copiar).grid(row=0, column=3)

        # --- Saída: título + botão ouvir ---
        topo_out = tk.Frame(corpo, bg=BG)
        topo_out.grid(row=3, column=0, sticky="ew", pady=(0, 5))
        topo_out.columnconfigure(0, weight=1)
        self.lbl_titulo_out = tk.Label(topo_out, font=FONT, bg=BG, fg=FG)
        self.lbl_titulo_out.grid(row=0, column=0, sticky="w")
        self._botao_pequeno(topo_out, "🔊 Ouvir tradução", self.ouvir_traducao).grid(row=0, column=1)

        self.saida = self._caixa_texto(corpo, row=4, estado="disabled")

    def _criar_rodape(self):
        self.status = tk.Label(
            self,
            text="Pronto  •  Ctrl+Enter para traduzir",
            font=("Segoe UI", 9),
            bg=BG_CARD,
            fg=FG_MUTED,
            anchor="w",
            padx=20,
            pady=6,
        )
        self.status.grid(row=3, column=0, sticky="ew", pady=(15, 0))

    def _criar_indicador_microfone(self):
        """Canvas que aparece por cima da caixa de entrada enquanto grava."""
        pai = self.entrada.master
        self.mic_canvas = tk.Canvas(
            pai, width=90, height=90, bg=BG_TEXT, highlightthickness=0
        )
        self._circulo = self.mic_canvas.create_oval(25, 25, 65, 65, fill=DANGER, outline="")
        self.mic_canvas.create_text(45, 45, text="🎤", font=("Segoe UI Emoji", 22), fill=BG)

    # ================= COMPONENTES =================
    def _caixa_texto(self, pai, row, estado):
        frame = tk.Frame(pai, bg=BG_CARD, padx=2, pady=2)
        frame.grid(row=row, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        texto = tk.Text(
            frame, wrap="word", font=FONT, bg=BG_TEXT, fg=FG,
            insertbackground=FG, relief="flat", padx=10, pady=10,
            height=5, state=estado,
        )
        texto.grid(row=0, column=0, sticky="nsew")

        scroll = tk.Scrollbar(frame, command=texto.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        texto.configure(yscrollcommand=scroll.set)
        return texto

    def _botao(self, pai, texto, comando, primario=False):
        bg = ACCENT if primario else BG_CARD
        fg = BG if primario else FG
        hover = ACCENT_HOVER if primario else BG_TEXT

        btn = tk.Button(
            pai, text=texto, command=comando,
            font=("Segoe UI", 11, "bold" if primario else "normal"),
            bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
            relief="flat", cursor="hand2", padx=20, pady=8, bd=0,
        )
        btn.bind("<Enter>", lambda e: btn.configure(bg=hover) if str(btn["state"]) == "normal" else None)
        btn.bind("<Leave>", lambda e: btn.configure(bg=bg))
        btn._bg_normal = bg
        return btn

    def _botao_pequeno(self, pai, texto, comando):
        btn = tk.Button(
            pai, text=texto, command=comando, font=("Segoe UI", 9),
            bg=BG_CARD, fg=FG, activebackground=BG_TEXT, activeforeground=FG,
            relief="flat", cursor="hand2", padx=10, pady=3, bd=0,
        )
        return btn

    # ================= ESTADO / IDIOMAS =================
    def atualizar_rotulos(self):
        nome_o = IDIOMAS[self.origem][0]
        nome_d = IDIOMAS[self.destino][0]
        self.lbl_origem.configure(text=nome_o)
        self.lbl_destino.configure(text=nome_d)
        self.lbl_titulo_in.configure(text=f"Texto em {nome_o}")
        self.lbl_titulo_out.configure(text=f"Tradução em {nome_d}")
        self.title(f"Tradutor {self.origem.upper()} ⇄ {self.destino.upper()}")

    def trocar_idiomas(self):
        if self.gravando:
            return
        self.origem, self.destino = self.destino, self.origem

        # A tradução passa a ser o novo texto de entrada
        traducao = self.saida.get("1.0", "end").strip()
        self.entrada.delete("1.0", "end")
        if traducao:
            self.entrada.insert("1.0", traducao)
        self._definir_saida("")

        self.atualizar_rotulos()
        self.status.configure(text="Idiomas trocados")
        if traducao:
            self.traduzir()

    def _definir_saida(self, texto):
        self.saida.configure(state="normal")
        self.saida.delete("1.0", "end")
        self.saida.insert("1.0", texto)
        self.saida.configure(state="disabled")

    # ================= TRADUÇÃO =================
    def traduzir(self):
        texto = self.entrada.get("1.0", "end").strip()
        if not texto:
            messagebox.showwarning("Aviso", "Escreva ou fale algum texto para traduzir.")
            return

        self.btn_traduzir.configure(state="disabled", text="A traduzir...")
        self.status.configure(text="A traduzir...")
        threading.Thread(
            target=self._traduzir_thread,
            args=(texto, self.origem, self.destino),
            daemon=True,
        ).start()

    def _traduzir_thread(self, texto, origem, destino):
        try:
            r = tradutor.translate(texto, src=origem, dest=destino)
            self.after(0, self._mostrar_resultado, r.text)
        except Exception as erro:
            self.after(0, self._mostrar_erro, str(erro))

    def _mostrar_resultado(self, traducao):
        self._definir_saida(traducao)
        self.btn_traduzir.configure(state="normal", text="Traduzir")
        self.status.configure(text="Tradução concluída  •  clique em 🔊 para ouvir")

    def _mostrar_erro(self, erro):
        self.btn_traduzir.configure(state="normal", text="Traduzir")
        self.status.configure(text="Erro na tradução")
        messagebox.showerror("Erro", f"Não foi possível traduzir:\n{erro}")

    # ================= MICROFONE =================
    def iniciar_gravacao(self):
        if sr is None or sd is None:
            messagebox.showerror(
                "Biblioteca em falta",
                "Instale com:\npip install SpeechRecognition sounddevice",
            )
            return
        if self.gravando:
            return

        self.gravando = True
        self.btn_mic.configure(state="disabled", text="🎤 A ouvir...")
        self.btn_trocar.configure(state="disabled")
        self.mic_canvas.place(relx=0.5, rely=0.5, anchor="center")
        self._animar_microfone()

        threading.Thread(
            target=self._ouvir_thread, args=(IDIOMAS[self.origem][1],), daemon=True
        ).start()

    def _animar_microfone(self):
        if not self.gravando:
            return
        self._fase += 0.35
        r = 16 + 5 * math.sin(self._fase)
        self.mic_canvas.coords(self._circulo, 45 - r, 45 - r, 45 + r, 45 + r)
        self.after(60, self._animar_microfone)

    def _ouvir_thread(self, codigo_voz):
        reconhecedor = sr.Recognizer()
        try:
            self.after(0, self.status.configure, {"text": "A ouvir... fale agora"})
            audio = gravar_voz()

            self.after(0, self.status.configure, {"text": "A reconhecer a voz..."})
            texto = reconhecedor.recognize_google(audio, language=codigo_voz)
            self.after(0, self._voz_reconhecida, texto)

        except TimeoutError:
            self.after(0, self._fim_gravacao, "Não ouvi nada. Tente de novo.")
        except sr.UnknownValueError:
            self.after(0, self._fim_gravacao, "Não consegui perceber o que disse.")
        except sr.RequestError as e:
            self.after(0, self._fim_gravacao, f"Erro no serviço de voz (sem internet?): {e}")
        except Exception as e:
            self.after(0, self._fim_gravacao, f"Microfone indisponível ou erro: {e}")

    def _voz_reconhecida(self, texto):
        self.entrada.delete("1.0", "end")
        self.entrada.insert("1.0", texto)
        self._fim_gravacao("Voz captada  •  a traduzir...")
        self.traduzir()

    def _fim_gravacao(self, mensagem):
        self.gravando = False
        self.mic_canvas.place_forget()
        self.btn_mic.configure(state="normal", text="🎤 Falar")
        self.btn_trocar.configure(state="normal")
        self.status.configure(text=mensagem)

    # ================= VOZ (TEXTO → ÁUDIO) =================
    def ouvir_original(self):
        texto = self.entrada.get("1.0", "end").strip()
        self._falar(texto, self.origem)

    def ouvir_traducao(self):
        texto = self.saida.get("1.0", "end").strip()
        self._falar(texto, self.destino)

    def _falar(self, texto, idioma):
        if not texto:
            messagebox.showinfo("Aviso", "Não há texto para ouvir.")
            return
        if gTTS is None:
            messagebox.showerror("Biblioteca em falta", "Instale com:\npip install gTTS")
            return
        self.status.configure(text="A preparar áudio...")
        threading.Thread(
            target=self._falar_thread, args=(texto, idioma), daemon=True
        ).start()

    def _falar_thread(self, texto, idioma):
        try:
            memoria = io.BytesIO()
            gTTS(text=texto, lang=idioma).write_to_fp(memoria)

            self.after(0, self.status.configure, {"text": "🔊 A reproduzir..."})
            tocar_mp3(memoria.getvalue())
            self.after(0, self.status.configure, {"text": "Pronto"})
        except Exception as e:
            self.after(0, self.status.configure, {"text": f"Erro no áudio: {e}"})

    # ================= UTILITÁRIOS =================
    def limpar(self):
        if self.gravando:
            return
        self.entrada.delete("1.0", "end")
        self._definir_saida("")
        self.status.configure(text="Pronto  •  Ctrl+Enter para traduzir")
        self.entrada.focus_set()

    def copiar(self):
        texto = self.saida.get("1.0", "end").strip()
        if texto:
            self.clipboard_clear()
            self.clipboard_append(texto)
            self.status.configure(text="Tradução copiada")


if __name__ == "__main__":
    App().mainloop()