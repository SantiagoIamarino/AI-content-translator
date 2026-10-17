# Cómo funciona el doblaje, explicado simple

Esto no es documentación formal. Es una explicación para entender qué hace el
programa con tu video, dónde se traba, dónde pierde tiempo y qué cosas podés
decidir vos. Los números de ejemplo son del gameplay del 16 de octubre
(82 minutos).

---

## La idea en una frase

El programa **escucha tu micrófono en español, lo pasa a texto, lo traduce al
inglés, genera esa frase con tu voz clonada y la pega en el mismo momento del
video**, encima del audio del juego, que no se toca.

## Las cinco palabras que hacen falta

- **Frase (o "cue")**: un pedazo de lo que dijiste, con su momento de inicio y
  de fin en el video. El gameplay del 16 quedó partido en **821 frases**.
- **Whisper**: el programa que "escucha" audio y lo pasa a texto. Es una IA de
  reconocimiento de voz que corre en tu computadora.
- **Luna**: la IA de texto (GPT-6 Luna, por tu cuenta de ChatGPT) que traduce y
  revisa. **No escucha audio; solo lee texto.**
- **Qwen**: la IA que genera la voz en inglés imitando tu grabación de
  referencia "tranquila".
- **Toma**: cada intento de Qwen de decir una frase. Como a veces sale mal, se
  generan varias y se elige la mejor.

---

## El recorrido, paso a paso

### 1. Revisar el video

Lee los datos del archivo: duración, pistas de audio y formato. También calcula
una "huella digital" del video completo para asegurarse de que nadie lo cambió
entre una corrida y otra.

- **Tarda** entre 26 y 78 segundos, y lo repite **cada vez** que se arranca o se
  reanuda.
- **Puede fallar si** el video no está en la ruta o cambió.

### 2. Separar los audios

Tu video tiene tres pistas: la mezcla, el juego solo y el micrófono solo.
Saca el micrófono y el juego como archivos separados. Al micrófono lo usa para
entender qué dijiste; al juego lo guarda intacto para el final.

- **Tarda** unos segundos.
- **Ojo:** cuál pista es cuál se indica a mano en cada grabación (mic=2,
  juego=1, mezcla=0 en la tuya). Si se indica mal, dobla el audio equivocado.

### 3. Escuchar y pasar a texto

Es más complejo de lo que parece. Hace cuatro cosas:

1. **Primera escucha:** Whisper escucha el micrófono en tramos de 10 minutos y
   devuelve el texto con la hora aproximada de cada palabra.
2. **Cortar en frases:** usa los silencios y el volumen para decidir dónde
   empieza y termina cada frase. Si hay dos frases muy pegadas (menos de 0,35 s
   entre ellas) las une, hasta un máximo de 10 segundos.
3. **Segunda escucha:** vuelve a escuchar con Whisper (el mismo modelo, con
   otra configuración) tres tipos de casos:
   - **Posibles repeticiones:** si dos frases seguidas parecen iguales, decide
     si dijiste lo mismo dos veces o si fue un error de Whisper.
   - **Palabras dudosas:** si Whisper no estaba seguro de alguna palabra,
     escucha esa frase otra vez. **Si la segunda escucha no da exactamente el
     mismo texto, guarda las dos versiones.** Esto es clave para entender los
     problemas, ver más abajo.
   - **Zonas con sonido pero sin texto:** si hay sonido de voz donde no se
     transcribió nada, intenta entender qué se dijo. Si no lo entiende con
     seguridad, lo marca como "ininteligible" y no inventa nada.
4. **Muletillas y pausas:** marca vacilaciones ("eh…") y pausas tuyas, para que
   el inglés también las tenga y no suene acelerado.

- **Tarda** unos 4 minutos y medio para 82 minutos de video.
- **Puede fallar en dos cosas:**
  - Las horas de cada palabra son aproximadas; a veces una palabra queda con
    duración cero.
  - La segunda escucha trabaja con un recorte más justo del audio, así que a
    veces se "come" la primera o la última palabra. **Eso crea "dos versiones
    distintas" de una frase aunque hayas dicho una sola cosa clara.**

### 4. Entender de qué trata el video

Luna lee la transcripción completa y arma un resumen, el tono con el que
hablás, un glosario de nombres y términos del juego (para traducirlos siempre
igual) y notas de estilo.

- **Tarda** segundos: 1 o 2 consultas a Luna.

### 5. Traducir

Luna traduce las frases en tandas de hasta 40. Para cada frase recibe:

- el español y las frases vecinas, para tener contexto;
- cuántas sílabas en inglés entran en el tiempo disponible;
- si hubo dos versiones de lo que dijiste, **las dos**, para que elija la
  que tiene sentido;
- las muletillas y pausas.

- **Tarda** unos 5 minutos en total (42 consultas en el job del 16).

### 6. Revisar la traducción

Una segunda pasada de Luna, en modo "revisor", compara español e inglés frase
por frase. Por cada frase puede decir:

- **ok**: está bien;
- **revisar**: la corrige y propone otra versión;
- **disputada**: no se sabe bien qué se dijo en español (por ejemplo, si dijiste
  "sé" o "no sé").

Hay como máximo **2 rondas**. La segunda solo revisa las frases que se
corrigieron o quedaron en duda. Una corrección necesita que una ronda
posterior diga "ok" a ese texto exacto.

- **El problema:** si la corrección llega en la última ronda, ya no queda nadie
  que la confirme, y **esa frase no se dobla**.

### 7. Resolver dudas sobre lo que dijiste ("resolución de fuente")

**Aquí se pierde la mayor parte del comentario hoy.**

Toda frase que tenga "dos versiones" de lo escuchado (paso 3), o que el
revisor dejó en duda, pasa por una revisión extra:

1. Se escucha el fragmento una vez más, con un poco de margen antes y después.
2. Luna recibe las transcripciones con lo que Whisper creyó oír y qué tan
   seguro estaba de cada palabra. **No recibe el audio.** Tiene que decidir qué
   dijiste y llenar un formulario estricto, que incluye copiar un código largo
   de 64 caracteres.
3. Un control automático revisa ese formulario con reglas muy exigentes. La
   principal: la versión que Luna elige tiene que coincidir con el recorte de
   la última escucha. Como ese recorte suele comerse palabras del borde, el
   control **rechaza la versión completa y correcta**.
4. Si el control rechaza, Luna recibe el error y reintenta. Ante ese error,
   a veces termina diciendo "no estoy seguro" sin evidencia nueva.

Hay hasta 2 rondas, más un reintento por frase. Si se agotan, la frase **queda
sin doblar entera**, aunque la duda fuera una sola palabra en una frase de
25 segundos.

**Ejemplo real (frase 2, 13 segundos):** la primera escucha dijo "…así que
bueno, espero que nos vaya bien…". La segunda escucha dijo lo mismo pero sin el
"bueno". La traducción estaba bien y el revisor la aprobó. Igual, el control
rechazó la respuesta porque no era idéntica al recorte, y se perdieron los 13
segundos.

**En números (job del 16):**

- 124 frases tenían "dos versiones" y solo 17 llegaron a doblarse.
- 107 de las 115 frases perdidas están en ese grupo.
- La mitad de las respuestas de Luna fueron rechazadas por el control (99 de
  202).
- En 53 frases perdidas, Luna y el revisor estuvieron de acuerdo en que todo
  estaba bien; solo el control las frenó.

**Lo que sí funciona:** cuando la duda es real, por ejemplo "3300" contra "300",
o "sé" contra "no sé", el sistema no se arriesga y no la dobla. Eso está bien y
hay que conservarlo.

### 8. El filtro final: ¿se dobla o no?

Antes de generar voz, cada frase pasa por un "semáforo". No se dobla si pasa
alguna de estas cosas:

- quedó una duda de lo que dijiste sin resolver (paso 7);
- la traducción quedó corregida pero sin confirmar (paso 6);
- el revisor la marcó como disputada;
- la frase se superpone con otra o es imposible por tiempo;
- en un intento anterior se decidió dejarla sin resolver.

Las frases frenadas acá **no se intentan generar**. Por eso casi ninguna de las
115 perdidas tuvo un problema de voz: nunca llegaron a generarse.

### 9. Generar la voz y encajarla en el video

**Es el paso más largo.** Para cada frase aprobada:

1. **Genera hasta 4 tomas buenas** con Qwen y tu voz de referencia. Si alguna
   sale mal, genera otra de reemplazo, hasta 4 extra.
2. **Verifica cada toma escuchándola:** Whisper escucha el inglés generado y lo
   compara con el texto que debía decir. Rechaza la toma si faltan palabras,
   cambió una negación o un número, se repite, se corta, tiene pausas raras
   de más de 1 segundo, habla demasiado rápido o lento, o no suena a tu voz
   (comparando tono y brillo).
3. **Elige la mejor** de las válidas: la que tiene mejor ritmo parecido al tuyo,
   suena más parecida a tu referencia y es más coherente con las frases ya
   elegidas.
4. **Encaja en el tiempo.** La frase tiene un espacio: desde que empezás a
   hablar hasta que empieza la frase siguiente.
   - Si la toma es más larga, puede **acelerarla hasta un 10 %** como máximo.
   - Si aun así no entra, puede adelantarla hasta 0,4 s si antes había
     silencio, salvo en reacciones a algo del juego.
   - Si aun así no entra, le pide a Luna una **versión más corta** de la frase
     (como máximo 2 veces). Esa versión corta vuelve a pasar por la revisión
     del paso 6.
5. **Cuida el final:** no corta el final natural de la voz (el "aire" al
   terminar). Si ese final no entra en el espacio, descarta la toma.

- **Tarda** unas **2 horas y 13 minutos** para el job del 16 (unas 3.600
  tomas). Cada toma son unos 3 segundos de Qwen más la verificación.
- **Puede fallar en dos casos:**
  - Frases 402 y 127: cálculo desparejo. Calcula la aceleración sin contar el
    final protegido y después descubre que, con ese final, se pasa por **5
    milésimas de segundo**, y la descarta. Una aceleración del 1 % la salvaría.
  - Frase 457: la frase realmente no entra (haría falta acelerar un 24 %).
    Ese caso está bien que quede afuera.

### 10. Mezclar y exportar

Pega todas las voces en inglés sobre el audio del juego, sin tocar el juego.
Si una voz satura, baja solo esa voz. Copia la imagen sin recomprimirla y arma
el MP4 final más los subtítulos.

- **Tarda** unos **5 minutos y medio**.
- El MP4 pesa unos 26 GB porque copia la imagen original en 1440p a 60 fps.

### 11. Controlar el resultado

Hace unos 35 controles automáticos: que el video se pueda reproducir, que la
imagen sea idéntica a la original, que el juego no haya cambiado, que ninguna
voz pise a otra, que los finales estén completos, que cada frase colocada
dice lo aprobado, etc.

- Si falta doblar alguna frase, o queda una zona ininteligible o una duda, el
  resultado es **"parcial"** (`english_PARTIAL.mp4`) y no "completo". Sale igual,
  con un reporte de qué frases faltan y por qué.
- **Tarda** unos **7 minutos**. Gran parte es volver a calcular la huella
  digital de archivos de más de 25 GB.

---

## Quién maneja todo esto

- **El director (`bin/aidub auto`)** ejecuta los pasos en orden. Cuando
  necesita a Luna (traducir, revisar, resolver dudas, acortar), la llama y
  sigue. Guarda todo lo hecho: si se corta, al reanudar no repite lo que ya
  estaba bien ni vuelve a pagar consultas ya respondidas.
- **El supervisor nocturno (`scripts/overnight.py`)** vigila al director
  durante la noche:
  - lo relanza solo si el programa "se cae" (hasta 2 veces);
  - si el director se detiene por un problema con Luna, **el supervisor también
    se detiene y espera a una persona**.
  - Eso pasó la noche del 16: a las 2:23 (hora argentina) un lote de traducción
    falló y todo quedó parado **casi 9 horas** hasta que alguien lo relanzó. Ese
    fallo puntual ya se corrigió, porque ahora una frase problemática no frena
    a todas; pero si Luna no responde por un rato, el supervisor sigue sin
    reintentar más tarde.

---

## Cuántas veces se reintenta cada cosa

| Qué | Cuántas veces | Qué pasa si se agota |
|---|---|---|
| Cada consulta a Luna | 2 intentos; el segundo le muestra el error del primero | Se reintenta solo con las frases que fallaron |
| Reintento de las frases que fallaron | 1 | Esas frases no se doblan; las demás siguen |
| Rondas de revisión de la traducción | 2 | Si la última corrige, queda sin confirmar y no se dobla |
| Rondas para resolver dudas de lo que dijiste | 2, más 1 escucha extra | La frase no se dobla |
| Tomas de voz por frase | 4 buenas, hasta 4 extra | Si no hay ninguna buena, no se dobla |
| Aceleración | hasta 10 %, en 2 ajustes | Se pide versión más corta |
| Versiones más cortas de una frase | 2 | Queda sin resolver |
| Whisper si se traba al verificar | reintenta en la placa, después en el procesador | Se detiene y se puede reanudar |
| Supervisor nocturno | 2 relanzamientos si el programa se cae | Espera a una persona |

---

## Resumen del gameplay del 16

**Dónde se pierde comentario** (115 frases, unos 7 minutos de espacios sin
voz; no es exactamente habla perdida):

```
821 frases
 ├─ 706 dobladas
 └─ 115 sin doblar
      ├─ 107 por "dos versiones" de lo que dijiste → frenadas en el paso 7
      │     ├─ 53 donde todos (traductor, revisor y Luna) decían que estaba bien
      │     ├─ ~20 con dudas reales o importantes (números, "no", quién hizo qué)
      │     └─ el resto: casos mixtos o donde Luna se rindió tras el error
      ├─ 3 por corrección sin confirmar o en duda (paso 6)
      ├─ 2 por respuestas rechazadas de la revisión
      ├─ 2 porque el final de la voz no entra (402 por milésimas, 457 de verdad)
      └─ 1 porque se dejó "sin resolver" tras acortarla (127)
```

**Dónde se va el tiempo:**

| Qué | Tiempo aproximado |
|---|---|
| Generar y verificar voces (paso 9) | ~2 h 13 min |
| Consultas a Luna, todas juntas | ~36 min (más de la mitad en el paso 7) |
| Mezcla y controles finales | ~12 min por pasada |
| Transcripción | ~4,5 min |
| Programa parado esperando a una persona | **~8,8 h** |

Total de la noche: 12,8 horas, de las cuales unas 2,8 fueron trabajo real.

---

## Qué podés decidir vos

Estas son las palancas reales. Cualquier indicación tuya en estos términos me
sirve para ajustar el plan.

1. **¿Cuánta seguridad querés a cambio de cuánta cobertura?**
   - **Opción conservadora (la propuesta):** se doblan las frases donde la
     única diferencia entre las dos escuchas es menor y el revisor aprobó la
     traducción; se frenan solo las dudas con "no", números o, si el revisor lo
     marca, quién hizo qué. Esperable: de 706 a unas 760–778 frases.
   - **Más estricta:** como hoy, se pierden muchas frases correctas.
   - **Más permisiva:** doblar casi todo y aceptar algún error de sentido
     ocasional.
2. **¿Preferís perder una frase entera o que te "falte" un pedacito?** Hoy, si
   hay una duda en una frase de 25 segundos, se pierde toda. Se puede cortar en
   frases más cortas (2–8 s) para perder solo el pedacito dudoso. A cambio,
   hay más cortes entre frases, que conviene escuchar para ver si suena natural.
3. **¿Querés escuchar una muestra antes de cada export?** Por ejemplo, 15–20
   frases recuperadas, unos 30 minutos tuyos. Es la única forma real de saber
   si las traducciones dudosas están bien.
4. **¿Vale la pena etiquetar una vez unas 60 frases?** Escucharías el español y
   dirías qué dijiste realmente (60–90 minutos, una sola vez). Con eso puedo
   medir cada cambio sin adivinar.
5. **Velocidad.** Lo que más tarda es generar 4 tomas buenas por frase. Bajar a
   2 tomas ahorraría mucho tiempo, pero podría empeorar la naturalidad. Habría
   que probarlo escuchando; por ahora está en pausa.
6. **Noches sin supervisión.** ¿Querés que, si Luna no responde, el programa
   espere y reintente más tarde? ¿O que, si Luna queda caída, exporte igual lo
   que ya tiene traducido, marcado como "parcial por falla de servicio"?
7. **Zonas ininteligibles.** Hoy hacen que el resultado nunca sea "completo",
   aunque no haya nada que doblar ahí. ¿Querés que se informen pero no impidan
   el "completo"?
8. **Segunda opinión de verdad.** La segunda escucha usa el mismo Whisper, así
   que no aporta una opinión independiente. Se podría descargar otro modelo
   más grande (~2,9 GB) solo para las dudas importantes. Es opcional y
   requiere tu autorización.
