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
        SupportedDistribution::Norm { loc, scale } => Some(StatNormal::new(*loc, *scale).ok()?.cdf(x)),
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
        .map(|value| distribution_cdf(dist, *value).unwrap_or(0.5).clamp(EPS, 1.0 - EPS))
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
        .map(|iteration_index| {
            let mut rng =
                rand::rngs::StdRng::seed_from_u64(iteration_seed(resolved_seed, iteration_index));
            let mut simulated = Vec::with_capacity(sample_size);

            for _ in 0..sample_size {
                match dist.sample_one(&mut rng) {
                    value if value.is_finite() => simulated.push(value),
                    _ => return (0usize, 0usize),
                }
            }

            let stat = match ad_statistic(&mut simulated, dist) {
                Some(value) if value.is_finite() => value,
                _ => return (0usize, 0usize),
            };

            if stat >= observed_stat {
                (1usize, 1usize)
            } else {
                (0usize, 1usize)
            }
        })
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
    py: Python<'_>,
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
) -> PyResult<(Option<f64>, Option<f64>, Option<f64>, Option<f64>, Option<f64>, u32)> {
    let fitted_params = fitted_params
        .as_slice()
        .map_err(|_| PyValueError::new_err("fitted_params must be a contiguous float64 array"))?;
    let sample_values = sample_values
        .as_slice()
        .map_err(|_| PyValueError::new_err("sample_values must be a contiguous float64 array"))?;

    let mut flags: u32 = 0;
    if sample_values.is_empty() {
        return Ok((None, None, None, None, None, 0b0001));
    }
    if sample_values.iter().any(|v| !v.is_finite()) {
        return Ok((None, None, None, None, None, 0b0010));
    }

    let dist = match SupportedDistribution::from_name_and_params(distribution, &fitted_params) {
        Some(value) => value,
        None => return Ok((None, None, None, None, None, 0b0100)),
    };
    if !dist.params_valid() {
        return Ok((None, None, None, None, None, 0b1000));
    }

    let mut nll = 0.0;
    for value in sample_values.iter() {
        let logpdf = distribution_logpdf(&dist, *value);
        match logpdf {
            Some(v) if v.is_finite() => nll -= v,
            _ => {
                flags |= 0b1_0000;
                return Ok((None, None, None, None, None, flags));
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
    Ok((Some(nll), Some(aic), Some(bic), ad, ks, flags))
}

#[pymodule]
fn _metroliza_distribution_fit_native(_py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_ad_ks_statistics, m)?)?;
    m.add_function(wrap_pyfunction!(estimate_ad_pvalue_monte_carlo, m)?)?;
    m.add_function(wrap_pyfunction!(compute_candidate_metrics, m)?)?;
    Ok(())
}
