use numpy::PyReadonlyArray1;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rand::SeedableRng;
use rand_distr::{Distribution, Gamma, Normal, Weibull};
use rayon::prelude::*;
use statrs::distribution::{
    Continuous, ContinuousCDF, Gamma as StatGamma, LogNormal as StatLogNormal,
    Normal as StatNormal, Weibull as StatWeibull,
};

const EPS: f64 = 1e-12;
const TWO_PI: f64 = std::f64::consts::PI * 2.0;

#[derive(Clone, Debug)]
enum SupportedDistribution {
    Norm {
        loc: f64,
        scale: f64,
    },
    SkewNorm {
        a: f64,
        loc: f64,
        scale: f64,
    },
    HalfNorm {
        loc: f64,
        scale: f64,
    },
    FoldNorm {
        c: f64,
        loc: f64,
        scale: f64,
    },
    Gamma {
        shape: f64,
        loc: f64,
        scale: f64,
    },
    WeibullMin {
        shape: f64,
        loc: f64,
        scale: f64,
    },
    LogNorm {
        sigma: f64,
        loc: f64,
        scale: f64,
    },
    JohnsonSu {
        gamma: f64,
        delta: f64,
        loc: f64,
        scale: f64,
    },
}

impl SupportedDistribution {
    fn from_name_and_params(name: &str, params: &[f64]) -> Option<Self> {
        match name {
            "norm" if params.len() == 2 => Some(Self::Norm {
                loc: params[0],
                scale: params[1],
            }),
            "skewnorm" if params.len() == 3 => Some(Self::SkewNorm {
                a: params[0],
                loc: params[1],
                scale: params[2],
            }),
            "halfnorm" if params.len() == 2 => Some(Self::HalfNorm {
                loc: params[0],
                scale: params[1],
            }),
            "foldnorm" if params.len() == 3 => Some(Self::FoldNorm {
                c: params[0],
                loc: params[1],
                scale: params[2],
            }),
            "gamma" if params.len() == 3 => Some(Self::Gamma {
                shape: params[0],
                loc: params[1],
                scale: params[2],
            }),
            "weibull_min" if params.len() == 3 => Some(Self::WeibullMin {
                shape: params[0],
                loc: params[1],
                scale: params[2],
            }),
            "lognorm" if params.len() == 3 => Some(Self::LogNorm {
                sigma: params[0],
                loc: params[1],
                scale: params[2],
            }),
            "johnsonsu" if params.len() == 4 => Some(Self::JohnsonSu {
                gamma: params[0],
                delta: params[1],
                loc: params[2],
                scale: params[3],
            }),
            _ => None,
        }
    }

    fn params_valid(&self) -> bool {
        match self {
            Self::Norm { scale, .. } | Self::HalfNorm { scale, .. } => *scale > 0.0,
            Self::SkewNorm { a, scale, .. } => a.is_finite() && *scale > 0.0,
            Self::FoldNorm { c, scale, .. } => c.is_finite() && *scale > 0.0,
            Self::Gamma { shape, scale, .. } => *shape > 0.0 && *scale > 0.0,
            Self::WeibullMin { shape, scale, .. } => *shape > 0.0 && *scale > 0.0,
            Self::LogNorm { sigma, scale, .. } => *sigma > 0.0 && *scale > 0.0,
            Self::JohnsonSu { delta, scale, .. } => *delta > 0.0 && *scale > 0.0,
        }
    }
}

#[derive(Clone)]
enum RuntimeDistribution {
    Norm {
        cdf: StatNormal,
        sampler: Normal<f64>,
    },
    SkewNorm {
        a: f64,
        loc: f64,
        scale: f64,
        sampler: Normal<f64>,
    },
    HalfNorm {
        loc: f64,
        scale: f64,
        standard_cdf: StatNormal,
        sampler: Normal<f64>,
    },
    FoldNorm {
        c: f64,
        loc: f64,
        scale: f64,
        standard_cdf: StatNormal,
        sampler: Normal<f64>,
    },
    Gamma {
        loc: f64,
        scale: f64,
        unit_cdf: StatGamma,
        sampler: Gamma<f64>,
    },
    WeibullMin {
        loc: f64,
        scale: f64,
        unit_cdf: StatWeibull,
        sampler: Weibull<f64>,
    },
    LogNorm {
        loc: f64,
        scale: f64,
        standard_cdf: StatLogNormal,
        sampler: Normal<f64>,
    },
    JohnsonSu {
        gamma: f64,
        delta: f64,
        loc: f64,
        scale: f64,
        standard_cdf: StatNormal,
        sampler: Normal<f64>,
    },
}

impl RuntimeDistribution {
    fn compile(dist: &SupportedDistribution) -> Option<Self> {
        match dist {
            SupportedDistribution::Norm { loc, scale } => Some(Self::Norm {
                cdf: StatNormal::new(*loc, *scale).ok()?,
                sampler: Normal::new(*loc, *scale).ok()?,
            }),
            SupportedDistribution::SkewNorm { a, loc, scale } => Some(Self::SkewNorm {
                a: *a,
                loc: *loc,
                scale: *scale,
                sampler: Normal::new(0.0, 1.0).ok()?,
            }),
            SupportedDistribution::HalfNorm { loc, scale } => Some(Self::HalfNorm {
                loc: *loc,
                scale: *scale,
                standard_cdf: StatNormal::new(0.0, 1.0).ok()?,
                sampler: Normal::new(0.0, *scale).ok()?,
            }),
            SupportedDistribution::FoldNorm { c, loc, scale } => Some(Self::FoldNorm {
                c: *c,
                loc: *loc,
                scale: *scale,
                standard_cdf: StatNormal::new(0.0, 1.0).ok()?,
                sampler: Normal::new(c * scale, *scale).ok()?,
            }),
            SupportedDistribution::Gamma { shape, loc, scale } => Some(Self::Gamma {
                loc: *loc,
                scale: *scale,
                unit_cdf: StatGamma::new(*shape, 1.0).ok()?,
                sampler: Gamma::new(*shape, *scale).ok()?,
            }),
            SupportedDistribution::WeibullMin { shape, loc, scale } => Some(Self::WeibullMin {
                loc: *loc,
                scale: *scale,
                unit_cdf: StatWeibull::new(*shape, 1.0).ok()?,
                sampler: Weibull::new(*scale, *shape).ok()?,
            }),
            SupportedDistribution::LogNorm { sigma, loc, scale } => Some(Self::LogNorm {
                loc: *loc,
                scale: *scale,
                standard_cdf: StatLogNormal::new(0.0, *sigma).ok()?,
                sampler: Normal::new(scale.ln(), *sigma).ok()?,
            }),
            SupportedDistribution::JohnsonSu {
                gamma,
                delta,
                loc,
                scale,
            } => Some(Self::JohnsonSu {
                gamma: *gamma,
                delta: *delta,
                loc: *loc,
                scale: *scale,
                standard_cdf: StatNormal::new(0.0, 1.0).ok()?,
                sampler: Normal::new(0.0, 1.0).ok()?,
            }),
        }
    }

    fn sample_one(&self, rng: &mut rand::rngs::StdRng) -> f64 {
        match self {
            Self::Norm { sampler, .. } => sampler.sample(rng),
            Self::SkewNorm {
                a,
                loc,
                scale,
                sampler,
            } => {
                let delta = *a / (1.0 + a * a).sqrt();
                let u0 = sampler.sample(rng);
                let u1 = sampler.sample(rng);
                loc + scale * (delta * u0.abs() + (1.0 - delta * delta).sqrt() * u1)
            }
            Self::HalfNorm { loc, sampler, .. } => loc + sampler.sample(rng).abs(),
            Self::FoldNorm { loc, sampler, .. } => loc + sampler.sample(rng).abs(),
            Self::Gamma { loc, sampler, .. } => loc + sampler.sample(rng),
            Self::WeibullMin { loc, sampler, .. } => loc + sampler.sample(rng),
            Self::LogNorm { loc, sampler, .. } => loc + sampler.sample(rng).exp(),
            Self::JohnsonSu {
                gamma,
                delta,
                loc,
                scale,
                sampler,
                ..
            } => {
                let z = sampler.sample(rng);
                let x = ((z - gamma) / delta).sinh();
                loc + scale * x
            }
        }
    }

    fn cdf(&self, x: f64) -> f64 {
        match self {
            Self::Norm { cdf, .. } => cdf.cdf(x),
            Self::SkewNorm { a, loc, scale, .. } => {
                let z = (x - loc) / scale;
                (standard_normal_cdf(z) - 2.0 * owen_t(z, *a)).clamp(0.0, 1.0)
            }
            Self::HalfNorm {
                loc,
                scale,
                standard_cdf,
                ..
            } => {
                if x <= *loc {
                    return 0.0;
                }
                let z = (x - loc) / scale;
                (2.0 * standard_cdf.cdf(z) - 1.0).clamp(0.0, 1.0)
            }
            Self::FoldNorm {
                c,
                loc,
                scale,
                standard_cdf,
                ..
            } => {
                if x <= *loc {
                    return 0.0;
                }
                let z = (x - loc) / scale;
                (standard_cdf.cdf(z - c) - standard_cdf.cdf(-z - c)).clamp(0.0, 1.0)
            }
            Self::Gamma {
                loc,
                scale,
                unit_cdf,
                ..
            } => {
                if x <= *loc {
                    return 0.0;
                }
                let shifted = (x - loc) / scale;
                unit_cdf.cdf(shifted)
            }
            Self::WeibullMin {
                loc,
                scale,
                unit_cdf,
                ..
            } => {
                if x <= *loc {
                    return 0.0;
                }
                let shifted = (x - loc) / scale;
                unit_cdf.cdf(shifted)
            }
            Self::LogNorm {
                loc,
                scale,
                standard_cdf,
                ..
            } => {
                if x <= *loc {
                    return 0.0;
                }
                let shifted = (x - loc) / scale;
                if shifted <= 0.0 {
                    return 0.0;
                }
                standard_cdf.cdf(shifted)
            }
            Self::JohnsonSu {
                gamma,
                delta,
                loc,
                scale,
                standard_cdf,
                ..
            } => {
                let y = (x - loc) / scale;
                let transformed = gamma + delta * y.asinh();
                standard_cdf.cdf(transformed)
            }
        }
    }
}

fn ad_statistic(sample: &mut [f64], dist: &RuntimeDistribution) -> Option<f64> {
    if sample.is_empty() {
        return None;
    }
    sample.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let n = sample.len() as f64;
    let probabilities: Vec<f64> = sample
        .iter()
        .map(|value| dist.cdf(*value).clamp(EPS, 1.0 - EPS))
        .collect();

    let mut sum = 0.0;
    for (i, p) in probabilities.iter().enumerate() {
        let idx = (i + 1) as f64;
        let rp = (1.0 - probabilities[sample.len() - 1 - i]).clamp(EPS, 1.0);
        sum += (2.0 * idx - 1.0) * (p.ln() + rp.ln());
    }
    Some(-n - (sum / n))
}

fn ks_statistic(sample: &[f64], dist: &RuntimeDistribution) -> Option<f64> {
    if sample.is_empty() {
        return None;
    }
    let mut sorted = sample.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let n = sorted.len() as f64;
    let mut d_plus = 0.0_f64;
    let mut d_minus = 0.0_f64;

    for (i, value) in sorted.iter().enumerate() {
        let rank = (i + 1) as f64;
        let cdf = dist.cdf(*value).clamp(0.0, 1.0);
        let plus = rank / n - cdf;
        let minus = cdf - (rank - 1.0) / n;
        if plus > d_plus {
            d_plus = plus;
        }
        if minus > d_minus {
            d_minus = minus;
        }
    }
    Some(d_plus.max(d_minus))
}

fn standard_normal_pdf(x: f64) -> f64 {
    (-0.5 * x * x).exp() / TWO_PI.sqrt()
}

fn standard_normal_cdf(x: f64) -> f64 {
    0.5 * (1.0 + statrs::function::erf::erf(x / std::f64::consts::SQRT_2))
}

fn owen_t(h: f64, a: f64) -> f64 {
    if a == 0.0 {
        return 0.0;
    }
    let sign = if a < 0.0 { -1.0 } else { 1.0 };
    let upper = a.abs();
    let steps = 64usize;
    let delta = upper / steps as f64;
    let integrand = |t: f64| (-0.5 * h * h * (1.0 + t * t)).exp() / (1.0 + t * t);
    let mut sum = 0.0;
    for idx in 0..=steps {
        let t = idx as f64 * delta;
        let coeff = if idx == 0 || idx == steps {
            1.0
        } else if idx % 2 == 0 {
            2.0
        } else {
            4.0
        };
        sum += coeff * integrand(t);
    }
    sign * (delta / 3.0) * sum / TWO_PI
}

fn distribution_cdf(dist: &SupportedDistribution, x: f64) -> Option<f64> {
    match dist {
        SupportedDistribution::Norm { loc, scale } => {
            Some(StatNormal::new(*loc, *scale).ok()?.cdf(x))
        }
        SupportedDistribution::SkewNorm { a, loc, scale } => {
            let z = (x - *loc) / *scale;
            Some((standard_normal_cdf(z) - 2.0 * owen_t(z, *a)).clamp(0.0, 1.0))
        }
        SupportedDistribution::HalfNorm { loc, scale } => {
            if x <= *loc {
                return Some(0.0);
            }
            let z = (x - loc) / scale;
            Some((2.0 * standard_normal_cdf(z) - 1.0).clamp(0.0, 1.0))
        }
        SupportedDistribution::FoldNorm { c, loc, scale } => {
            if x <= *loc {
                return Some(0.0);
            }
            let z = (x - loc) / scale;
            Some((standard_normal_cdf(z - c) - standard_normal_cdf(-z - c)).clamp(0.0, 1.0))
        }
        SupportedDistribution::Gamma { shape, loc, scale } => {
            if x <= *loc {
                return Some(0.0);
            }
            let shifted = (x - loc) / scale;
            Some(StatGamma::new(*shape, 1.0).ok()?.cdf(shifted))
        }
        SupportedDistribution::WeibullMin { shape, loc, scale } => {
            if x <= *loc {
                return Some(0.0);
            }
            let shifted = (x - loc) / scale;
            Some(StatWeibull::new(*shape, 1.0).ok()?.cdf(shifted))
        }
        SupportedDistribution::LogNorm { sigma, loc, scale } => {
            if x <= *loc {
                return Some(0.0);
            }
            let shifted = (x - loc) / scale;
            if shifted <= 0.0 {
                return Some(0.0);
            }
            Some(StatLogNormal::new(0.0, *sigma).ok()?.cdf(shifted))
        }
        SupportedDistribution::JohnsonSu {
            gamma,
            delta,
            loc,
            scale,
        } => {
            let y = (x - loc) / scale;
            let transformed = gamma + delta * y.asinh();
            Some(standard_normal_cdf(transformed))
        }
    }
}

fn distribution_logpdf(dist: &SupportedDistribution, x: f64) -> Option<f64> {
    match dist {
        SupportedDistribution::Norm { loc, scale } => {
            let z = (x - *loc) / *scale;
            Some(-0.5 * z * z - scale.ln() - 0.5 * TWO_PI.ln())
        }
        SupportedDistribution::SkewNorm { a, loc, scale } => {
            let z = (x - *loc) / *scale;
            let phi = standard_normal_pdf(z);
            let cdf_term = standard_normal_cdf(a * z);
            let pdf = 2.0 * phi * cdf_term / *scale;
            if pdf <= 0.0 {
                None
            } else {
                Some(pdf.ln())
            }
        }
        SupportedDistribution::HalfNorm { loc, scale } => {
            if x < *loc {
                return None;
            }
            let z = (x - *loc) / *scale;
            let logpdf = (2.0_f64).ln() - scale.ln() - 0.5 * TWO_PI.ln() - 0.5 * z * z;
            Some(logpdf)
        }
        SupportedDistribution::FoldNorm { c, loc, scale } => {
            if x < *loc {
                return None;
            }
            let z = (x - *loc) / *scale;
            let density = (standard_normal_pdf(z - c) + standard_normal_pdf(z + c)) / *scale;
            if density <= 0.0 {
                None
            } else {
                Some(density.ln())
            }
        }
        SupportedDistribution::Gamma { shape, loc, scale } => {
            if x <= *loc {
                return None;
            }
            let shifted = (x - *loc) / *scale;
            let density = StatGamma::new(*shape, 1.0).ok()?.pdf(shifted) / *scale;
            if density <= 0.0 {
                None
            } else {
                Some(density.ln())
            }
        }
        SupportedDistribution::WeibullMin { shape, loc, scale } => {
            if x <= *loc {
                return None;
            }
            let shifted = (x - *loc) / *scale;
            let density = StatWeibull::new(*shape, 1.0).ok()?.pdf(shifted) / *scale;
            if density <= 0.0 {
                None
            } else {
                Some(density.ln())
            }
        }
        SupportedDistribution::LogNorm { sigma, loc, scale } => {
            if x <= *loc {
                return None;
            }
            let shifted = (x - *loc) / *scale;
            let density = StatLogNormal::new(0.0, *sigma).ok()?.pdf(shifted) / *scale;
            if density <= 0.0 {
                None
            } else {
                Some(density.ln())
            }
        }
        SupportedDistribution::JohnsonSu {
            gamma,
            delta,
            loc,
            scale,
        } => {
            let y = (x - *loc) / *scale;
            let u = gamma + delta * y.asinh();
            let density = (delta / (*scale * (1.0 + y * y).sqrt())) * standard_normal_pdf(u);
            if density <= 0.0 {
                None
            } else {
                Some(density.ln())
            }
        }
    }
}

fn ad_statistic_with_cdf(sample: &[f64], dist: &SupportedDistribution) -> Option<f64> {
    if sample.is_empty() {
        return None;
    }
    let mut sorted = sample.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let n = sorted.len() as f64;
    let probabilities: Vec<f64> = sorted
        .iter()
        .map(|value| {
            distribution_cdf(dist, *value)
                .unwrap_or(0.5)
                .clamp(EPS, 1.0 - EPS)
        })
        .collect();

    let mut sum = 0.0;
    for (i, p) in probabilities.iter().enumerate() {
        let idx = (i + 1) as f64;
        let rp = (1.0 - probabilities[sorted.len() - 1 - i]).clamp(EPS, 1.0);
        sum += (2.0 * idx - 1.0) * (p.ln() + rp.ln());
    }
    Some(-n - (sum / n))
}

fn ks_statistic_with_cdf(sample: &[f64], dist: &SupportedDistribution) -> Option<f64> {
    if sample.is_empty() {
        return None;
    }
    let mut sorted = sample.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let n = sorted.len() as f64;
    let mut d_plus = 0.0_f64;
    let mut d_minus = 0.0_f64;
    for (i, value) in sorted.iter().enumerate() {
        let rank = (i + 1) as f64;
        let cdf = distribution_cdf(dist, *value)?.clamp(0.0, 1.0);
        d_plus = d_plus.max(rank / n - cdf);
        d_minus = d_minus.max(cdf - (rank - 1.0) / n);
    }
    Some(d_plus.max(d_minus))
}

fn sample_mean(sample: &[f64]) -> Option<f64> {
    if sample.is_empty() {
        return None;
    }
    Some(sample.iter().sum::<f64>() / sample.len() as f64)
}

fn sample_variance(sample: &[f64], mean: f64) -> Option<f64> {
    if sample.is_empty() {
        return None;
    }
    Some(
        sample
            .iter()
            .map(|value| {
                let delta = *value - mean;
                delta * delta
            })
            .sum::<f64>()
            / sample.len() as f64,
    )
}

fn sample_skewness(sample: &[f64], mean: f64, variance: f64) -> Option<f64> {
    if sample.is_empty() || variance <= 0.0 {
        return None;
    }
    let m3 = sample
        .iter()
        .map(|value| {
            let delta = *value - mean;
            delta * delta * delta
        })
        .sum::<f64>()
        / sample.len() as f64;
    Some(m3 / variance.powf(1.5))
}

fn bisection_root<F>(mut low: f64, mut high: f64, f: F, tol: f64, max_iter: usize) -> Option<f64>
where
    F: Fn(f64) -> f64,
{
    let mut f_low = f(low);
    let mut f_high = f(high);
    if !(f_low.is_finite() && f_high.is_finite()) {
        return None;
    }
    if f_low == 0.0 {
        return Some(low);
    }
    if f_high == 0.0 {
        return Some(high);
    }
    if f_low.signum() == f_high.signum() {
        return None;
    }
    for _ in 0..max_iter {
        let mid = 0.5 * (low + high);
        let f_mid = f(mid);
        if !f_mid.is_finite() {
            return None;
        }
        if f_mid.abs() <= tol || (high - low).abs() <= tol {
            return Some(mid);
        }
        if f_low.signum() == f_mid.signum() {
            low = mid;
            f_low = f_mid;
        } else {
            high = mid;
            f_high = f_mid;
        }
    }
    let mid = 0.5 * (low + high);
    let f_mid = f(mid);
    if f_mid.is_finite() {
        Some(mid)
    } else if f_low.abs() < f_high.abs() {
        Some(low)
    } else {
        Some(high)
    }
}

fn nelder_mead<F>(
    initial: &[f64],
    step: &[f64],
    max_iter: usize,
    tol: f64,
    objective: F,
) -> Option<Vec<f64>>
where
    F: Fn(&[f64]) -> f64,
{
    let dim = initial.len();
    if dim == 0 || step.len() != dim {
        return None;
    }

    let mut simplex: Vec<Vec<f64>> = Vec::with_capacity(dim + 1);
    simplex.push(initial.to_vec());
    for axis in 0..dim {
        let mut point = initial.to_vec();
        let delta = if step[axis].is_finite() && step[axis] > 0.0 {
            step[axis]
        } else {
            0.1
        };
        point[axis] += delta;
        simplex.push(point);
    }
    let mut values: Vec<f64> = simplex.iter().map(|point| objective(point)).collect();

    let alpha = 1.0;
    let gamma = 2.0;
    let rho = 0.5;
    let sigma = 0.5;

    for _ in 0..max_iter {
        let mut order: Vec<usize> = (0..simplex.len()).collect();
        order.sort_by(|left, right| {
            values[*left]
                .partial_cmp(&values[*right])
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        simplex = order.iter().map(|idx| simplex[*idx].clone()).collect();
        values = order.iter().map(|idx| values[*idx]).collect();

        let best = &simplex[0];
        let best_value = values[0];
        let worst_value = values[dim];

        let max_value_delta = values
            .iter()
            .map(|value| (value - best_value).abs())
            .fold(0.0_f64, f64::max);
        let max_coord_delta = simplex
            .iter()
            .skip(1)
            .flat_map(|point| {
                point
                    .iter()
                    .zip(best.iter())
                    .map(|(value, base)| (value - base).abs())
            })
            .fold(0.0_f64, f64::max);
        if max_value_delta <= tol && max_coord_delta <= tol {
            return if best_value.is_finite() {
                Some(best.clone())
            } else {
                None
            };
        }

        let mut centroid = vec![0.0; dim];
        for point in simplex.iter().take(dim) {
            for axis in 0..dim {
                centroid[axis] += point[axis];
            }
        }
        for axis in 0..dim {
            centroid[axis] /= dim as f64;
        }

        let worst = &simplex[dim];
        let reflected: Vec<f64> = (0..dim)
            .map(|axis| centroid[axis] + alpha * (centroid[axis] - worst[axis]))
            .collect();
        let reflected_value = objective(&reflected);

        if reflected_value < values[0] {
            let expanded: Vec<f64> = (0..dim)
                .map(|axis| centroid[axis] + gamma * (reflected[axis] - centroid[axis]))
                .collect();
            let expanded_value = objective(&expanded);
            if expanded_value < reflected_value {
                simplex[dim] = expanded;
                values[dim] = expanded_value;
            } else {
                simplex[dim] = reflected;
                values[dim] = reflected_value;
            }
            continue;
        }

        if reflected_value < values[dim - 1] {
            simplex[dim] = reflected;
            values[dim] = reflected_value;
            continue;
        }

        let contracted: Vec<f64> = if reflected_value < worst_value {
            (0..dim)
                .map(|axis| centroid[axis] + rho * (reflected[axis] - centroid[axis]))
                .collect()
        } else {
            (0..dim)
                .map(|axis| centroid[axis] + rho * (worst[axis] - centroid[axis]))
                .collect()
        };
        let contracted_value = objective(&contracted);
        if contracted_value < worst_value {
            simplex[dim] = contracted;
            values[dim] = contracted_value;
            continue;
        }

        let best_point = simplex[0].clone();
        for idx in 1..simplex.len() {
            for axis in 0..dim {
                simplex[idx][axis] =
                    best_point[axis] + sigma * (simplex[idx][axis] - best_point[axis]);
            }
            values[idx] = objective(&simplex[idx]);
        }
    }

    let mut best_idx = 0usize;
    for idx in 1..values.len() {
        if values[idx] < values[best_idx] {
            best_idx = idx;
        }
    }
    if values[best_idx].is_finite() {
        Some(simplex[best_idx].clone())
    } else {
        None
    }
}

fn negative_log_likelihood(dist: &SupportedDistribution, sample: &[f64]) -> Option<f64> {
    let mut nll = 0.0;
    for value in sample {
        let logpdf = distribution_logpdf(dist, *value)?;
        if !logpdf.is_finite() {
            return None;
        }
        nll -= logpdf;
    }
    Some(nll)
}

fn fit_norm_params(sample: &[f64]) -> Option<Vec<f64>> {
    let mean = sample_mean(sample)?;
    let variance = sample_variance(sample, mean)?;
    let scale = variance.sqrt();
    if !scale.is_finite() || scale <= 0.0 {
        return None;
    }
    Some(vec![mean, scale])
}

fn fit_halfnorm_params(sample: &[f64], force_loc_zero: bool) -> Option<Vec<f64>> {
    let loc = if force_loc_zero {
        if sample.iter().any(|value| *value < 0.0) {
            return None;
        }
        0.0
    } else {
        sample
            .iter()
            .copied()
            .fold(f64::INFINITY, f64::min)
    };
    let mean_sq = sample
        .iter()
        .map(|value| {
            let shifted = *value - loc;
            shifted * shifted
        })
        .sum::<f64>()
        / sample.len() as f64;
    let scale = mean_sq.sqrt();
    if !scale.is_finite() || scale <= 0.0 {
        return None;
    }
    Some(vec![loc, scale])
}

fn fit_lognorm_params(sample: &[f64], force_loc_zero: bool) -> Option<Vec<f64>> {
    if !force_loc_zero || sample.iter().any(|value| *value <= 0.0) {
        return None;
    }
    let log_values: Vec<f64> = sample.iter().map(|value| value.ln()).collect();
    let mean_log = sample_mean(&log_values)?;
    let variance_log = sample_variance(&log_values, mean_log)?;
    let sigma = variance_log.sqrt();
    let scale = mean_log.exp();
    if !sigma.is_finite() || sigma <= 0.0 || !scale.is_finite() || scale <= 0.0 {
        return None;
    }
    Some(vec![sigma, 0.0, scale])
}

fn fit_gamma_params(sample: &[f64], force_loc_zero: bool) -> Option<Vec<f64>> {
    if !force_loc_zero || sample.iter().any(|value| *value <= 0.0) {
        return None;
    }
    let xbar = sample_mean(sample)?;
    if !xbar.is_finite() || xbar <= 0.0 {
        return None;
    }
    let mean_log = sample.iter().map(|value| value.ln()).sum::<f64>() / sample.len() as f64;
    let s = xbar.ln() - mean_log;
    if !s.is_finite() || s <= 0.0 {
        return None;
    }

    let aest = (3.0 - s + ((s - 3.0) * (s - 3.0) + 24.0 * s).sqrt()) / (12.0 * s);
    if !aest.is_finite() || aest <= 0.0 {
        return None;
    }

    let gamma_eq = |a: f64| a.ln() - statrs::function::gamma::digamma(a) - s;
    let mut low = (aest * 0.6).max(1e-6);
    let mut high = (aest * 1.4).max(low * 2.0);
    let mut f_low = gamma_eq(low);
    let mut f_high = gamma_eq(high);
    for _ in 0..48 {
        if f_low.is_finite() && f_high.is_finite() && f_low.signum() != f_high.signum() {
            break;
        }
        low = (low * 0.5).max(1e-8);
        high *= 2.0;
        f_low = gamma_eq(low);
        f_high = gamma_eq(high);
    }
    let shape = bisection_root(low, high, gamma_eq, 1e-12, 128)?;
    let scale = xbar / shape;
    if !scale.is_finite() || scale <= 0.0 {
        return None;
    }
    Some(vec![shape, 0.0, scale])
}

fn sample_percentile(sorted_sample: &[f64], probability: f64) -> Option<f64> {
    if sorted_sample.is_empty() {
        return None;
    }
    if sorted_sample.len() == 1 {
        return Some(sorted_sample[0]);
    }
    let bounded = probability.clamp(0.0, 1.0);
    let position = bounded * (sorted_sample.len() - 1) as f64;
    let lower_idx = position.floor() as usize;
    let upper_idx = position.ceil() as usize;
    if lower_idx == upper_idx {
        return Some(sorted_sample[lower_idx]);
    }
    let fraction = position - lower_idx as f64;
    Some(
        sorted_sample[lower_idx]
            + fraction * (sorted_sample[upper_idx] - sorted_sample[lower_idx]),
    )
}

fn foldnorm_mean_coefficient(c: f64) -> Option<f64> {
    if !c.is_finite() || c < 0.0 {
        return None;
    }
    let expfac = (-0.5 * c * c).exp() / TWO_PI.sqrt();
    Some(2.0 * expfac + c * statrs::function::erf::erf(c / std::f64::consts::SQRT_2))
}

fn foldnorm_variance_coefficient(c: f64) -> Option<f64> {
    let mean_coeff = foldnorm_mean_coefficient(c)?;
    let variance_coeff = c * c + 1.0 - mean_coeff * mean_coeff;
    if variance_coeff.is_finite() && variance_coeff >= 0.0 {
        Some(variance_coeff)
    } else {
        None
    }
}

fn fit_foldnorm_params(sample: &[f64], force_loc_zero: bool) -> Option<Vec<f64>> {
    if !force_loc_zero || sample.iter().any(|value| *value < 0.0) {
        return None;
    }
    let mean = sample_mean(sample)?;
    let variance = sample_variance(sample, mean)?;
    if !mean.is_finite() || mean <= 0.0 || !variance.is_finite() || variance < 0.0 {
        return None;
    }

    let halfnorm_mean = foldnorm_mean_coefficient(0.0)?;
    let halfnorm_variance = foldnorm_variance_coefficient(0.0)?;
    let halfnorm_ratio = halfnorm_variance / (halfnorm_mean * halfnorm_mean);
    let sample_ratio = variance / (mean * mean);
    let c_guess = if sample_ratio >= halfnorm_ratio - 1e-12 {
        0.0
    } else {
        let ratio_residual = |c: f64| {
            let mean_coeff = foldnorm_mean_coefficient(c).unwrap_or(f64::NAN);
            let variance_coeff = foldnorm_variance_coefficient(c).unwrap_or(f64::NAN);
            variance_coeff / (mean_coeff * mean_coeff) - sample_ratio
        };
        let mut high = 1.0_f64;
        let mut residual_high = ratio_residual(high);
        for _ in 0..64 {
            if residual_high.is_finite() && residual_high <= 0.0 {
                break;
            }
            high *= 2.0;
            residual_high = ratio_residual(high);
        }
        if residual_high.is_finite() && residual_high <= 0.0 {
            bisection_root(0.0, high, ratio_residual, 1e-12, 160).unwrap_or(0.0)
        } else {
            0.0
        }
    };

    let mean_coeff = foldnorm_mean_coefficient(c_guess)?;
    let scale_guess = mean / mean_coeff;
    if !scale_guess.is_finite() || scale_guess <= 0.0 {
        return None;
    }

    let initial = vec![c_guess.sqrt(), scale_guess.ln()];
    let step = vec![initial[0].max(0.35) * 0.2, 0.08];
    let solution = nelder_mead(&initial, &step, 160, 1e-8, |point| {
        if point.len() != 2 || !point.iter().all(|value| value.is_finite()) {
            return f64::INFINITY;
        }
        let dist = SupportedDistribution::FoldNorm {
            c: point[0] * point[0],
            loc: 0.0,
            scale: point[1].exp(),
        };
        negative_log_likelihood(&dist, sample).unwrap_or(f64::INFINITY)
    })?;
    let final_scale = solution[1].exp();
    if !final_scale.is_finite() || final_scale <= 0.0 {
        return None;
    }
    Some(vec![solution[0] * solution[0], 0.0, final_scale])
}

fn weibull_root_equation(shape: f64, log_values: &[f64], mean_log: f64) -> Option<f64> {
    if !shape.is_finite() || shape <= 0.0 {
        return None;
    }
    let max_term = log_values
        .iter()
        .map(|value| shape * *value)
        .fold(f64::NEG_INFINITY, f64::max);
    if !max_term.is_finite() {
        return None;
    }
    let mut weighted_sum = 0.0;
    let mut weighted_log_sum = 0.0;
    for log_value in log_values {
        let weight = (shape * *log_value - max_term).exp();
        weighted_sum += weight;
        weighted_log_sum += weight * *log_value;
    }
    if weighted_sum <= 0.0 || !weighted_sum.is_finite() {
        return None;
    }
    Some(weighted_log_sum / weighted_sum - mean_log - 1.0 / shape)
}

fn fit_weibull_min_params(sample: &[f64], force_loc_zero: bool) -> Option<Vec<f64>> {
    if !force_loc_zero || sample.iter().any(|value| *value <= 0.0) {
        return None;
    }
    let log_values: Vec<f64> = sample.iter().map(|value| value.ln()).collect();
    let mean_log = sample_mean(&log_values)?;
    let mut low = 0.1_f64;
    let mut high = 10.0_f64;
    let mut f_low = weibull_root_equation(low, &log_values, mean_log)?;
    let mut f_high = weibull_root_equation(high, &log_values, mean_log)?;
    for _ in 0..64 {
        if f_low.signum() != f_high.signum() {
            break;
        }
        low *= 0.5;
        high *= 2.0;
        f_low = weibull_root_equation(low, &log_values, mean_log)?;
        f_high = weibull_root_equation(high, &log_values, mean_log)?;
    }
    let shape = bisection_root(
        low,
        high,
        |value| weibull_root_equation(value, &log_values, mean_log).unwrap_or(f64::NAN),
        1e-12,
        160,
    )?;
    let max_term = log_values
        .iter()
        .map(|value| shape * *value)
        .fold(f64::NEG_INFINITY, f64::max);
    let mean_exp = log_values
        .iter()
        .map(|value| (shape * *value - max_term).exp())
        .sum::<f64>()
        / sample.len() as f64;
    let scale = ((mean_exp.ln() + max_term) / shape).exp();
    if !scale.is_finite() || scale <= 0.0 {
        return None;
    }
    Some(vec![shape, 0.0, scale])
}

fn fit_skewnorm_params(sample: &[f64]) -> Option<Vec<f64>> {
    let mean = sample_mean(sample)?;
    let variance = sample_variance(sample, mean)?;
    let scale_norm = variance.sqrt();
    if !scale_norm.is_finite() || scale_norm <= 0.0 {
        return None;
    }
    let skewness = sample_skewness(sample, mean, variance).unwrap_or(0.0);
    let clipped_skewness = skewness.clamp(-0.99, 0.99);
    let s_23 = clipped_skewness.abs().powf(2.0 / 3.0);
    let delta = if s_23 <= 0.0 {
        0.0
    } else {
        let denom = s_23 + (((4.0 - std::f64::consts::PI) / 2.0).powf(2.0 / 3.0));
        (std::f64::consts::PI / 2.0 * s_23 / denom).sqrt() * clipped_skewness.signum()
    };
    let delta_sq = (delta * delta).clamp(0.0, 0.995);
    let shape = if delta_sq <= 0.0 {
        0.0
    } else {
        (delta_sq / (1.0 - delta_sq)).sqrt() * clipped_skewness.signum()
    };
    let scale = (variance / (1.0 - 2.0 * delta_sq / std::f64::consts::PI)).sqrt();
    if !scale.is_finite() || scale <= 0.0 {
        return Some(vec![0.0, mean, scale_norm]);
    }
    let loc = mean - scale * delta * (2.0 / std::f64::consts::PI).sqrt();
    let initial = vec![shape, loc, scale.ln()];
    let step = vec![
        shape.abs().max(0.35) * 0.2,
        scale.max(scale_norm) * 0.15,
        0.08,
    ];
    let solution = nelder_mead(&initial, &step, 120, 1e-8, |point| {
        if point.len() != 3 || !point.iter().all(|value| value.is_finite()) {
            return f64::INFINITY;
        }
        let dist = SupportedDistribution::SkewNorm {
            a: point[0],
            loc: point[1],
            scale: point[2].exp(),
        };
        negative_log_likelihood(&dist, sample).unwrap_or(f64::INFINITY)
    })?;
    let final_scale = solution[2].exp();
    if !final_scale.is_finite() || final_scale <= 0.0 {
        return None;
    }
    Some(vec![solution[0], solution[1], final_scale])
}

fn fit_johnsonsu_profile(sample: &[f64], loc: f64, scale: f64) -> Option<(f64, f64, f64)> {
    if !loc.is_finite() || !scale.is_finite() || scale <= 0.0 {
        return None;
    }
    let transformed: Vec<f64> = sample
        .iter()
        .map(|value| ((*value - loc) / scale).asinh())
        .collect();
    let mean = sample_mean(&transformed)?;
    let variance = sample_variance(&transformed, mean)?;
    let std = variance.sqrt();
    if !std.is_finite() || std <= 0.0 {
        return None;
    }
    let delta = 1.0 / std;
    let gamma = -mean * delta;
    let dist = SupportedDistribution::JohnsonSu {
        gamma,
        delta,
        loc,
        scale,
    };
    let nll = negative_log_likelihood(&dist, sample)?;
    Some((gamma, delta, nll))
}

fn fit_johnsonsu_params(sample: &[f64]) -> Option<Vec<f64>> {
    let mean = sample_mean(sample)?;
    let variance = sample_variance(sample, mean)?;
    let scale_norm = variance.sqrt();
    if !scale_norm.is_finite() || scale_norm <= 0.0 {
        return None;
    }

    let mut sorted_sample = sample.to_vec();
    sorted_sample.sort_by(|left, right| {
        left.partial_cmp(right)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let median = sample_percentile(&sorted_sample, 0.5)?;
    let q1 = sample_percentile(&sorted_sample, 0.25)?;
    let q3 = sample_percentile(&sorted_sample, 0.75)?;
    let p10 = sample_percentile(&sorted_sample, 0.10)?;
    let p90 = sample_percentile(&sorted_sample, 0.90)?;
    let iqr = (q3 - q1).abs();
    let robust_iqr_scale = iqr / 1.3489795003921634;
    let robust_tail_scale = (p90 - p10).abs() / 2.5631031310892007;

    let mut scale_candidates = vec![scale_norm, robust_iqr_scale, robust_tail_scale];
    scale_candidates.retain(|value| value.is_finite() && *value > EPS);
    if scale_candidates.is_empty() {
        return None;
    }

    let loc_candidates = vec![median, mean, 0.5 * (q1 + q3)];
    let mut best_profile: Option<(f64, f64, f64, f64, f64)> = None;
    for loc in loc_candidates {
        if !loc.is_finite() {
            continue;
        }
        for scale in &scale_candidates {
            if let Some((gamma, delta, nll)) = fit_johnsonsu_profile(sample, loc, *scale) {
                if !nll.is_finite() {
                    continue;
                }
                let is_better = best_profile
                    .as_ref()
                    .map(|(_, _, _, _, current_nll)| nll < *current_nll)
                    .unwrap_or(true);
                if is_better {
                    best_profile = Some((loc, *scale, gamma, delta, nll));
                }
            }
        }
    }

    let (initial_loc, initial_scale, initial_gamma, initial_delta, initial_nll) = best_profile?;
    let initial = vec![initial_loc, initial_scale.ln()];
    let step = vec![initial_scale.max(scale_norm) * 0.15, 0.08];
    let optimized = nelder_mead(&initial, &step, 220, 1e-8, |point| {
        if point.len() != 2 || !point.iter().all(|value| value.is_finite()) {
            return f64::INFINITY;
        }
        fit_johnsonsu_profile(sample, point[0], point[1].exp())
            .map(|(_, _, nll)| nll)
            .unwrap_or(f64::INFINITY)
    });

    if let Some(solution) = optimized {
        let final_loc = solution[0];
        let final_scale = solution[1].exp();
        if let Some((final_gamma, final_delta, final_nll)) =
            fit_johnsonsu_profile(sample, final_loc, final_scale)
        {
            if final_nll.is_finite() && final_nll <= initial_nll {
                return Some(vec![final_gamma, final_delta, final_loc, final_scale]);
            }
        }
    }

    Some(vec![
        initial_gamma,
        initial_delta,
        initial_loc,
        initial_scale,
    ])
}

fn fit_candidate_params_impl(
    distribution: &str,
    sample_values: &[f64],
    force_loc_zero: bool,
) -> Option<Vec<f64>> {
    if sample_values.is_empty() || sample_values.iter().any(|value| !value.is_finite()) {
        return None;
    }
    match distribution {
        "norm" => fit_norm_params(sample_values),
        "skewnorm" => fit_skewnorm_params(sample_values),
        "halfnorm" => fit_halfnorm_params(sample_values, force_loc_zero),
        "foldnorm" => fit_foldnorm_params(sample_values, force_loc_zero),
        "gamma" => fit_gamma_params(sample_values, force_loc_zero),
        "weibull_min" => fit_weibull_min_params(sample_values, force_loc_zero),
        "lognorm" => fit_lognorm_params(sample_values, force_loc_zero),
        "johnsonsu" => fit_johnsonsu_params(sample_values),
        _ => None,
    }
}

fn splitmix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9E37_79B9_7F4A_7C15);
    value = (value ^ (value >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    value ^ (value >> 31)
}

fn iteration_seed(base_seed: u64, iteration_index: usize) -> u64 {
    splitmix64(base_seed ^ (iteration_index as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15))
}

fn run_ad_monte_carlo(
    dist: &RuntimeDistribution,
    sample_size: usize,
    observed_stat: f64,
    iterations: usize,
    resolved_seed: u64,
) -> (Option<f64>, usize) {
    let (exceed_count, valid_trials) = (0..iterations)
        .into_par_iter()
        .map_init(
            || Vec::with_capacity(sample_size),
            |simulated, iteration_index| {
                let mut rng = rand::rngs::StdRng::seed_from_u64(iteration_seed(
                    resolved_seed,
                    iteration_index,
                ));
                simulated.clear();

                for _ in 0..sample_size {
                    match dist.sample_one(&mut rng) {
                        value if value.is_finite() => simulated.push(value),
                        _ => return (0usize, 0usize),
                    }
                }

                let stat = match ad_statistic(simulated, dist) {
                    Some(value) if value.is_finite() => value,
                    _ => return (0usize, 0usize),
                };

                if stat >= observed_stat {
                    (1usize, 1usize)
                } else {
                    (0usize, 1usize)
                }
            },
        )
        .reduce(
            || (0usize, 0usize),
            |left, right| (left.0 + right.0, left.1 + right.1),
        );

    if valid_trials == 0 {
        return (None, 0);
    }
    let p_value = (exceed_count as f64 + 1.0) / (valid_trials as f64 + 1.0);
    (Some(p_value), valid_trials)
}

#[pyfunction]
#[pyo3(signature = (distribution, fitted_params, sample_values))]
fn compute_ad_ks_statistics(
    _py: Python<'_>,
    distribution: &str,
    fitted_params: PyReadonlyArray1<'_, f64>,
    sample_values: PyReadonlyArray1<'_, f64>,
) -> PyResult<(f64, f64)> {
    let fitted_params = fitted_params
        .as_slice()
        .map_err(|_| PyValueError::new_err("fitted_params must be a contiguous float64 array"))?;
    let sample_values = sample_values
        .as_slice()
        .map_err(|_| PyValueError::new_err("sample_values must be a contiguous float64 array"))?;

    let dist = SupportedDistribution::from_name_and_params(distribution, &fitted_params)
        .ok_or_else(|| {
            PyValueError::new_err("Unsupported distribution identifier or invalid parameter count")
        })?;

    if !dist.params_valid() {
        return Err(PyValueError::new_err("Invalid distribution parameters"));
    }

    if sample_values.is_empty() {
        return Err(PyValueError::new_err("sample_values must not be empty"));
    }

    if sample_values.iter().any(|v| !v.is_finite()) {
        return Err(PyValueError::new_err("sample_values must be finite"));
    }
    let runtime_dist = RuntimeDistribution::compile(&dist)
        .ok_or_else(|| PyValueError::new_err("Invalid distribution parameters"))?;

    let mut ad_sample = sample_values.to_vec();
    let ad = ad_statistic(&mut ad_sample, &runtime_dist)
        .ok_or_else(|| PyValueError::new_err("Unable to compute Anderson-Darling statistic"))?;
    let ks = ks_statistic(&sample_values, &runtime_dist)
        .ok_or_else(|| PyValueError::new_err("Unable to compute Kolmogorov-Smirnov statistic"))?;
    Ok((ad, ks))
}

#[pyfunction]
#[pyo3(signature = (distribution, fitted_params, sample_size, observed_stat, iterations, seed=None))]
fn estimate_ad_pvalue_monte_carlo(
    py: Python<'_>,
    distribution: &str,
    fitted_params: PyReadonlyArray1<'_, f64>,
    sample_size: usize,
    observed_stat: f64,
    iterations: usize,
    seed: Option<u64>,
) -> PyResult<(Option<f64>, usize)> {
    if iterations == 0 {
        return Ok((None, 0));
    }
    if sample_size == 0 {
        return Ok((None, 0));
    }

    let fitted_params = fitted_params
        .as_slice()
        .map_err(|_| PyValueError::new_err("fitted_params must be a contiguous float64 array"))?;

    let dist = SupportedDistribution::from_name_and_params(distribution, &fitted_params)
        .ok_or_else(|| {
            PyValueError::new_err("Unsupported distribution identifier or invalid parameter count")
        })?;

    if !dist.params_valid() {
        return Ok((None, 0));
    }
    let runtime_dist = RuntimeDistribution::compile(&dist)
        .ok_or_else(|| PyValueError::new_err("Invalid distribution parameters"))?;

    let resolved_seed = seed.unwrap_or_else(rand::random::<u64>);
    let result = py.allow_threads(|| {
        run_ad_monte_carlo(
            &runtime_dist,
            sample_size,
            observed_stat,
            iterations,
            resolved_seed,
        )
    });
    Ok(result)
}

#[pyfunction]
#[pyo3(signature = (distribution, fitted_params, sample_values))]
fn compute_candidate_metrics(
    distribution: &str,
    fitted_params: PyReadonlyArray1<'_, f64>,
    sample_values: PyReadonlyArray1<'_, f64>,
) -> PyResult<(
    Option<f64>,
    Option<f64>,
    Option<f64>,
    Option<f64>,
    Option<f64>,
    u32,
)> {
    let fitted_params = fitted_params
        .as_slice()
        .map_err(|_| PyValueError::new_err("fitted_params must be a contiguous float64 array"))?;
    let sample_values = sample_values
        .as_slice()
        .map_err(|_| PyValueError::new_err("sample_values must be a contiguous float64 array"))?;

    Ok(compute_candidate_metrics_impl(
        distribution,
        fitted_params,
        sample_values,
    ))
}

fn compute_candidate_metrics_impl(
    distribution: &str,
    fitted_params: &[f64],
    sample_values: &[f64],
) -> (
    Option<f64>,
    Option<f64>,
    Option<f64>,
    Option<f64>,
    Option<f64>,
    u32,
) {
    let mut flags: u32 = 0;
    if sample_values.is_empty() {
        return (None, None, None, None, None, 0b0001);
    }
    if sample_values.iter().any(|v| !v.is_finite()) {
        return (None, None, None, None, None, 0b0010);
    }

    let dist = match SupportedDistribution::from_name_and_params(distribution, &fitted_params) {
        Some(value) => value,
        None => return (None, None, None, None, None, 0b0100),
    };
    if !dist.params_valid() {
        return (None, None, None, None, None, 0b1000);
    }

    let mut nll = 0.0;
    for value in sample_values.iter() {
        let logpdf = distribution_logpdf(&dist, *value);
        match logpdf {
            Some(v) if v.is_finite() => nll -= v,
            _ => {
                flags |= 0b1_0000;
                return (None, None, None, None, None, flags);
            }
        }
    }
    let n = sample_values.len() as f64;
    let k = fitted_params.len() as f64;
    let aic = 2.0 * k + 2.0 * nll;
    let bic = k * n.ln() + 2.0 * nll;
    let ad = ad_statistic_with_cdf(sample_values, &dist);
    let ks = ks_statistic_with_cdf(sample_values, &dist);
    if ad.is_none() {
        flags |= 0b10_0000;
    }
    if ks.is_none() {
        flags |= 0b100_0000;
    }
    (Some(nll), Some(aic), Some(bic), ad, ks, flags)
}

#[pyfunction]
#[pyo3(signature = (distributions, fitted_params_batch, sample_values_batch))]
fn compute_candidate_metrics_batch(
    distributions: Vec<String>,
    fitted_params_batch: Vec<PyReadonlyArray1<'_, f64>>,
    sample_values_batch: Vec<PyReadonlyArray1<'_, f64>>,
) -> PyResult<(
    Vec<Option<f64>>,
    Vec<Option<f64>>,
    Vec<Option<f64>>,
    Vec<Option<f64>>,
    Vec<Option<f64>>,
    Vec<u32>,
)> {
    if distributions.len() != fitted_params_batch.len()
        || distributions.len() != sample_values_batch.len()
    {
        return Err(PyValueError::new_err(
            "distributions, fitted_params_batch, and sample_values_batch must have equal lengths",
        ));
    }

    let mut nll_values: Vec<Option<f64>> = Vec::with_capacity(distributions.len());
    let mut aic_values: Vec<Option<f64>> = Vec::with_capacity(distributions.len());
    let mut bic_values: Vec<Option<f64>> = Vec::with_capacity(distributions.len());
    let mut ad_values: Vec<Option<f64>> = Vec::with_capacity(distributions.len());
    let mut ks_values: Vec<Option<f64>> = Vec::with_capacity(distributions.len());
    let mut flags_values: Vec<u32> = Vec::with_capacity(distributions.len());

    for idx in 0..distributions.len() {
        let fitted_params = fitted_params_batch[idx].as_slice().map_err(|_| {
            PyValueError::new_err("fitted_params_batch entries must be contiguous float64 arrays")
        })?;
        let sample_values = sample_values_batch[idx].as_slice().map_err(|_| {
            PyValueError::new_err("sample_values_batch entries must be contiguous float64 arrays")
        })?;

        let (nll, aic, bic, ad, ks, flags) =
            compute_candidate_metrics_impl(&distributions[idx], fitted_params, sample_values);
        nll_values.push(nll);
        aic_values.push(aic);
        bic_values.push(bic);
        ad_values.push(ad);
        ks_values.push(ks);
        flags_values.push(flags);
    }

    Ok((
        nll_values,
        aic_values,
        bic_values,
        ad_values,
        ks_values,
        flags_values,
    ))
}

#[pyfunction]
#[pyo3(signature = (distributions, sample_values_batch, force_loc_zero_batch))]
fn compute_candidate_fit_params_batch(
    distributions: Vec<String>,
    sample_values_batch: Vec<PyReadonlyArray1<'_, f64>>,
    force_loc_zero_batch: Vec<bool>,
) -> PyResult<(Vec<Option<Vec<f64>>>, Vec<u32>)> {
    if distributions.len() != sample_values_batch.len()
        || distributions.len() != force_loc_zero_batch.len()
    {
        return Err(PyValueError::new_err(
            "distributions, sample_values_batch, and force_loc_zero_batch must have equal lengths",
        ));
    }

    let mut fitted_params_batch: Vec<Option<Vec<f64>>> = Vec::with_capacity(distributions.len());
    let mut flags_values: Vec<u32> = Vec::with_capacity(distributions.len());

    for idx in 0..distributions.len() {
        let sample_values = sample_values_batch[idx].as_slice().map_err(|_| {
            PyValueError::new_err("sample_values_batch entries must be contiguous float64 arrays")
        })?;

        if sample_values.is_empty() {
            fitted_params_batch.push(None);
            flags_values.push(0b0001);
            continue;
        }
        if sample_values.iter().any(|value| !value.is_finite()) {
            fitted_params_batch.push(None);
            flags_values.push(0b0010);
            continue;
        }

        let fitted = fit_candidate_params_impl(
            &distributions[idx],
            sample_values,
            force_loc_zero_batch[idx],
        );
        if let Some(params) = fitted {
            fitted_params_batch.push(Some(params));
            flags_values.push(0);
        } else {
            fitted_params_batch.push(None);
            flags_values.push(0b1000_0000);
        }
    }

    Ok((fitted_params_batch, flags_values))
}

#[pymodule]
fn _metroliza_distribution_fit_native(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_ad_ks_statistics, m)?)?;
    m.add_function(wrap_pyfunction!(estimate_ad_pvalue_monte_carlo, m)?)?;
    m.add_function(wrap_pyfunction!(compute_candidate_metrics, m)?)?;
    m.add_function(wrap_pyfunction!(compute_candidate_metrics_batch, m)?)?;
    m.add_function(wrap_pyfunction!(compute_candidate_fit_params_batch, m)?)?;
    Ok(())
}
