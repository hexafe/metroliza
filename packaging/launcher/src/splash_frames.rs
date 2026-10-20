//! Frames of the loading animation shown by the launcher splash.
//!
//! The GIF is the application's own loading animation (the "duck",
//! `metroliza.resources.base64_encoded_files.encoded_loading_gif`), committed decoded under
//! `assets/`; `tests/test_launcher_splash_asset.py` keeps the two byte-identical. Frames are
//! composited once into opaque pixels over the splash background, so painting a frame is a plain
//! blit: no per-tick decoding, no alpha blending and no dependency on the application runtime.

/// The loading animation, embedded in the launcher binary.
pub const LOADING_GIF: &[u8] = include_bytes!("../assets/metroliza_loading.gif");

/// Default frame delay for frames that declare none (GIF delay 0).
const DEFAULT_DELAY_MS: u32 = 100;
/// Upper bound on decoded frames, so a malformed asset cannot exhaust memory.
const MAX_FRAMES: usize = 512;
/// Upper bound on the logical screen, in pixels.
const MAX_PIXELS: usize = 1024 * 1024;

/// Fully composited animation frames.
#[derive(Debug)]
pub struct Frames {
    pub width: u32,
    pub height: u32,
    /// Display time of each frame in milliseconds.
    pub delays_ms: Vec<u32>,
    /// One top-down, opaque `0x00RRGGBB` buffer per frame: the byte order of a 32-bit
    /// `BI_RGB` device-independent bitmap on little-endian Windows.
    pub pixels: Vec<Vec<u32>>,
}

/// Pack an RGB colour as a `0x00RRGGBB` pixel.
pub const fn pixel(r: u8, g: u8, b: u8) -> u32 {
    ((r as u32) << 16) | ((g as u32) << 8) | (b as u32)
}

/// Decode `gif` and composite every frame over `background` (GIF disposal methods applied).
pub fn decode(gif_bytes: &[u8], background: u32) -> Result<Frames, String> {
    let mut options = gif::DecodeOptions::new();
    options.set_color_output(gif::ColorOutput::RGBA);
    let mut decoder = options
        .read_info(gif_bytes)
        .map_err(|e| format!("gif header: {e}"))?;
    let (width, height) = (usize::from(decoder.width()), usize::from(decoder.height()));
    if width == 0 || height == 0 || width * height > MAX_PIXELS {
        return Err(format!("unsupported gif size {width}x{height}"));
    }

    let mut canvas = vec![background; width * height];
    let mut pixels = Vec::new();
    let mut delays_ms = Vec::new();
    while let Some(frame) = decoder
        .read_next_frame()
        .map_err(|e| format!("gif frame {}: {e}", pixels.len()))?
    {
        if pixels.len() >= MAX_FRAMES {
            return Err("too many gif frames".into());
        }
        let restore = (frame.dispose == gif::DisposalMethod::Previous).then(|| canvas.clone());
        let (left, top) = (usize::from(frame.left), usize::from(frame.top));
        let (frame_width, frame_height) = (usize::from(frame.width), usize::from(frame.height));
        for y in 0..frame_height {
            let row = top + y;
            if row >= height {
                break;
            }
            for x in 0..frame_width {
                let column = left + x;
                if column >= width {
                    break;
                }
                let i = (y * frame_width + x) * 4;
                let Some(rgba) = frame.buffer.get(i..i + 4) else {
                    return Err("short gif frame buffer".into());
                };
                // GIF transparency is binary: a transparent pixel keeps what is below it.
                if rgba[3] != 0 {
                    canvas[row * width + column] = pixel(rgba[0], rgba[1], rgba[2]);
                }
            }
        }
        pixels.push(canvas.clone());
        let delay = u32::from(frame.delay) * 10;
        delays_ms.push(if delay == 0 { DEFAULT_DELAY_MS } else { delay });

        match frame.dispose {
            gif::DisposalMethod::Background => {
                for row in top..(top + frame_height).min(height) {
                    let start = row * width + left.min(width);
                    let end = row * width + (left + frame_width).min(width);
                    canvas[start..end].fill(background);
                }
            }
            gif::DisposalMethod::Previous => {
                if let Some(previous) = restore {
                    canvas = previous;
                }
            }
            _ => {}
        }
    }
    if pixels.is_empty() {
        return Err("gif has no frames".into());
    }
    Ok(Frames {
        width: width as u32,
        height: height as u32,
        delays_ms,
        pixels,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const BACKGROUND: u32 = pixel(0x15, 0x20, 0x2b);

    #[test]
    fn embedded_animation_decodes_into_opaque_frames() {
        let frames = decode(LOADING_GIF, BACKGROUND).expect("embedded gif decodes");
        assert_eq!((frames.width, frames.height), (220, 213));
        assert_eq!(frames.pixels.len(), 56);
        assert_eq!(frames.delays_ms.len(), 56);
        assert!(frames.delays_ms.iter().all(|&d| d == 100));
        for frame in &frames.pixels {
            assert_eq!(frame.len(), 220 * 213);
            assert!(frame.iter().all(|p| p >> 24 == 0), "pixels stay opaque 0x00RRGGBB");
        }
        // The animation moves: consecutive frames differ, and some pixels are not background.
        assert!(frames.pixels.windows(2).any(|w| w[0] != w[1]));
        assert!(frames.pixels[0].iter().any(|&p| p != BACKGROUND));
    }

    #[test]
    fn rejects_input_that_is_not_a_gif() {
        assert!(decode(b"not a gif", BACKGROUND).is_err());
        assert!(decode(&LOADING_GIF[..64], BACKGROUND).is_err());
    }
}
