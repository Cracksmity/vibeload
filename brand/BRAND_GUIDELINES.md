# VibeLoader — Guía de Marca (Play-Drop)

> Uso del símbolo, la paleta y la tipografía en la app de Windows, el instalador y el repositorio.
> Todo lo de `brand/master`, `brand/kit` y `assets/` se genera con `brand/build_playdrop.py`.

---

## 1. El símbolo: Play-Drop

Un **triángulo hacia abajo** con dos ranuras que bajan desde su borde superior.

- El triángulo es a la vez un **play girado** (video), una **flecha de descarga** (Loader) y una **V** (Vibe).
- Las ranuras dibujan **tres barras de ecualizador** (audio).
- La silueta queda entera: a 16 px, donde las ranuras ya no se distinguen, se sigue reconociendo el triángulo.

La geometría vive en un solo lugar, `vibeloader/ui/brand.py` (`MASTER_GEOM` y `SMALL_CUTS`). La usan la cabecera de la app y el script de generación, así que nunca se desincronizan.

### Versiones

| Versión | Archivo | Uso |
|---|---|---|
| Ícono de app (placa violeta) | `master/vibeload-app-icon.svg` | Barra de tareas, Inicio, instalador, `assets/icono.ico` |
| Símbolo sin placa | `master/vibeload-symbol*.svg` | Cabecera de la ventana, documentos, fondos propios |
| Bandeja del sistema | `master/vibeload-tray-*.svg` | Blanco puro, sin placa |
| Lockup horizontal | `master/vibeload-horizontal*.svg` | README, web, banners |
| Splash | `master/vibeload-splash.svg` → `assets/splash.png` | Arranque del `.exe` (480×270) |

### Cortes para tamaños chicos

Los tamaños **16, 20, 24, 32 y 48 px** no son reducciones del maestro: cada uno tiene su propia geometría con bordes rectos sobre píxeles enteros. El `.ico` de la app incluye todos esos cortes más 64, 128 y 256.

| Tamaño | Ranuras | Notas |
|---|---|---|
| 16 px | ninguna | Triángulo liso; las ranuras de 1 px se pierden en la placa |
| 20 px | 1 px | Escala de Windows al 125 % |
| 24 px | 2 px | Escala al 150 % |
| 32 / 48 px | 2 / 3 px | Barras de igual ancho |

### Área de protección y tamaño mínimo

- Margen libre alrededor del símbolo: **el ancho de una ranura × 2** (28 px en el lienzo de 256).
- Símbolo sin placa: mínimo **16 px** de alto. Lockup horizontal: mínimo **120 px** de ancho.

---

## 2. Paleta

Un solo acento de marca y colores de estado que significan algo. Las razones de contraste están medidas con WCAG 2.2.

### Marca

| Rol | Nombre | HEX | Uso |
|---|---|---|---|
| Acento | **Vibe Violet** | `#6D3DF2` | Placa del ícono, botón principal, barra de progreso. Texto blanco encima: **5,8:1** |
| Acento hover | — | `#7C52F5` | Hover del botón principal (4,8:1) |
| Acento presionado | — | `#5B2CD9` | Estado presionado; en tema claro también es el color de links (7,5:1) |
| Lavanda | **Lavanda** | `#B69CFF` | Símbolo, links, foco e íconos sobre fondo oscuro (8,4:1) |

### Neutros (tinte violeta)

| Token | Oscuro | Claro |
|---|---|---|
| Fondo | `#0F0D16` (Tinta) | `#F7F5FB` (Niebla) |
| Superficie | `#18151F` | `#FFFFFF` |
| Superficie 2 | `#221E2C` | `#EFEBF7` |
| Línea | `#2E2939` | `#DCD6E8` |
| Línea fuerte (bordes de controles, ≥ 3:1) | `#6E6782` | `#8E86A0` |
| Texto | `#F2EFF8` (17:1) | `#16131D` (17:1) |
| Texto atenuado | `#A39DB3` (7,4:1) | `#5E5770` (6,3:1) |

### Estados

| Estado | Oscuro | Claro |
|---|---|---|
| Listo | `#3DD68C` | `#13824F` |
| Error | `#FF6B7A` | `#C8283B` |
| Aviso | `#FFB547` | `#8F5300` |

Los tokens de la app están en `vibeloader/ui/styles.py` (`THEMES`). No se usan colores sueltos fuera de esa tabla.

---

## 3. Tipografía

- **Wordmark:** `vibeloader` en minúsculas, Segoe UI Bold convertido a contornos (lo genera el script).
- **Interfaz:** Segoe UI Variable (nativa de Windows, sin peso extra en el instalador).
  - Escala: 12 · 13 · 14 · 16 · 19 px. En la vista Simple todo sube un paso (texto base 15–16 px, botones grandes 19 px).
  - Monoespaciada (registro, cifras de la cola, pie de estado): Cascadia Mono / Consolas.

---

## 4. Lo que no se debe hacer

- ❌ Reducir el maestro para tamaños chicos: usar los cortes de `SMALL_CUTS`.
- ❌ Separar o mover las tres barras: el triángulo tiene que leerse como una sola pieza.
- ❌ Degradados, sombras o contornos sobre el símbolo.
- ❌ Usar el violeta de Tailwind (`#7C3AED`) del logo anterior ni otros acentos: un solo violeta, `#6D3DF2`.
- ❌ Colores por tipo de descarga (los botones de colores de la versión 3.0): el color marca el estado, no el formato.

---

## 5. Archivo

El logo anterior (Sonic V: cinco barras con la central desplazada) y sus exportaciones están en `brand/archive/sonic-v/`.
