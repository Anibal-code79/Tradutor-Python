from googletrans import Translator

tradutor= Translator()

texto= input("Escreva seu texto para traduzir: ")
linguagem = "en"

resultado= tradutor.translate(texto, dest= linguagem)

print(f"\nOriginal ({resultado.src}): {texto}")
print(f"Traducao  ({linguagem}): {resultado.text}")
