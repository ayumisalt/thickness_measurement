#include "analysis_io.hpp"

#include <TF1.h>
#include <TFitResult.h>
#include <TFitResultPtr.h>
#include <TGraphErrors.h>
#include <Math/ProbFuncMathCore.h>

#include <nlohmann/json.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <optional>
#include <regex>
#include <set>
#include <unordered_map>

namespace fs = std::filesystem;
using json = nlohmann::json;
using thickness::ThicknessRecord;

struct Point {
  double x{};
  double y{};
  double z{};
};

struct Track {
  int id{};
  std::vector<Point> points;
};

struct PolylineSample {
  Point point;
  cv::Point2d direction_xy;
};

class Polyline {
public:
  explicit Polyline(const Track &track) {
    for (const auto &point : track.points) {
      if (points_.empty() || distance_um(points_.back(), point) > 1e-12)
        points_.push_back(point);
    }
    if (points_.size() < 2)
      throw std::runtime_error("track " + std::to_string(track.id) +
                               " has zero 3D length");
    cumulative_um_.push_back(0.0);
    for (std::size_t i = 0; i + 1 < points_.size(); ++i) {
      segment_lengths_um_.push_back(distance_um(points_[i], points_[i + 1]));
      cumulative_um_.push_back(cumulative_um_.back() +
                               segment_lengths_um_.back());
    }
  }

  double length_um() const { return cumulative_um_.back(); }
  const std::vector<Point> &points() const { return points_; }

  PolylineSample sample(double distance) const {
    const auto upper = std::lower_bound(cumulative_um_.begin() + 1,
                                        cumulative_um_.end(), distance);
    const std::size_t segment = std::min<std::size_t>(
        std::distance(cumulative_um_.begin() + 1, upper),
        segment_lengths_um_.size() - 1);
    const Point &start = points_[segment];
    const Point &end = points_[segment + 1];
    const double fraction =
        (distance - cumulative_um_[segment]) / segment_lengths_um_[segment];
    Point point{start.x + fraction * (end.x - start.x),
                start.y + fraction * (end.y - start.y),
                start.z + fraction * (end.z - start.z)};

    std::size_t direction_segment = segment;
    double dx = end.x - start.x;
    double dy = end.y - start.y;
    if (std::hypot(dx, dy) <= 1e-15) {
      bool found = false;
      for (std::size_t offset = 1; offset < points_.size(); ++offset) {
        for (const long candidate_signed :
             {static_cast<long>(segment) - static_cast<long>(offset),
              static_cast<long>(segment) + static_cast<long>(offset)}) {
          if (candidate_signed < 0 ||
              candidate_signed >= static_cast<long>(segment_lengths_um_.size()))
            continue;
          const auto candidate = static_cast<std::size_t>(candidate_signed);
          dx = points_[candidate + 1].x - points_[candidate].x;
          dy = points_[candidate + 1].y - points_[candidate].y;
          if (std::hypot(dx, dy) > 1e-15) {
            direction_segment = candidate;
            found = true;
            break;
          }
        }
        if (found)
          break;
      }
      if (!found)
        throw std::runtime_error("track has no measurable XY projection");
      dx = points_[direction_segment + 1].x - points_[direction_segment].x;
      dy = points_[direction_segment + 1].y - points_[direction_segment].y;
    }
    const double xy_length = std::hypot(dx, dy);
    return {point, {dx / xy_length, dy / xy_length}};
  }

private:
  static double distance_um(const Point &left, const Point &right) {
    return 1000.0 * std::sqrt(std::pow(right.x - left.x, 2) +
                              std::pow(right.y - left.y, 2) +
                              std::pow(right.z - left.z, 2));
  }

  std::vector<Point> points_;
  std::vector<double> segment_lengths_um_;
  std::vector<double> cumulative_um_;
};

struct Frame {
  fs::path path;
  double z{};
};

struct Stack {
  fs::path json_path;
  int width{};
  int height{};
  std::array<double, 4> affine{};
  double origin_x{};
  double origin_y{};
  std::vector<Frame> frames;

  cv::Point2d stage_to_pixel(double x, double y) const {
    const double determinant = affine[0] * affine[3] - affine[1] * affine[2];
    const double dx = x - origin_x;
    const double dy = y - origin_y;
    return {(affine[3] * dx - affine[1] * dy) / determinant + width / 2.0,
            (-affine[2] * dx + affine[0] * dy) / determinant + height / 2.0};
  }

  double pixel_size_um() const {
    return std::sqrt(
               std::abs(affine[0] * affine[3] - affine[1] * affine[2])) *
           1000.0;
  }
};

struct Config {
  double spacing_um{1.0};
  double endpoint_margin_um{2.0};
  double profile_half_width_um{2.0};
  int focus_search_frames{25};
  int focus_window_px{15};
  int gaussian_kernel_px{101};
  double minimum_contrast{50.0};
};

Stack load_stack(const fs::path &path) {
  std::ifstream input(path);
  if (!input)
    throw std::runtime_error("cannot open " + path.string());
  json data;
  input >> data;
  const auto &affine = data.at("AffineP2S");
  const auto &images = data.at("Images");
  if (images.empty())
    throw std::runtime_error("image stack is empty");
  Stack stack;
  stack.json_path = fs::absolute(path);
  stack.width = data.at("ImageType").at("Width").get<int>();
  stack.height = data.at("ImageType").at("Height").get<int>();
  for (int i = 0; i < 4; ++i)
    stack.affine[i] = affine.at(i).get<double>();
  stack.origin_x = images.at(0).at("x").get<double>();
  stack.origin_y = images.at(0).at("y").get<double>();
  for (const auto &image : images)
    stack.frames.push_back(
        {(path.parent_path() / image.at("Path").get<std::string>()),
         image.at("z").get<double>()});
  return stack;
}

std::pair<std::vector<Track>, double>
load_tracks(const fs::path &path, const std::optional<double> &shrink_override) {
  std::ifstream input(path);
  if (!input)
    throw std::runtime_error("cannot open " + path.string());
  std::map<int, std::vector<Point>> grouped;
  double shrink = 1.0;
  const std::regex shrink_pattern(
      R"(^\s*#\s*Shrink\s*:\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)))",
      std::regex_constants::icase);
  std::string line;
  int line_number = 0;
  while (std::getline(input, line)) {
    ++line_number;
    std::smatch match;
    if (std::regex_search(line, match, shrink_pattern)) {
      shrink = std::stod(match[1]);
      continue;
    }
    const auto first = line.find_first_not_of(" \t\r\n");
    if (first == std::string::npos || line[first] == '#')
      continue;
    std::istringstream parser(line);
    std::vector<double> values;
    double value{};
    while (parser >> value)
      values.push_back(value);
    int track_id{};
    Point point;
    if (values.size() == 4) {
      track_id = static_cast<int>(values[0]);
      point = {values[1], values[2], values[3]};
    } else if (values.size() >= 5) {
      track_id = static_cast<int>(values[1]);
      point = {values[2], values[3], values[4]};
    } else {
      throw std::runtime_error(path.string() + ":" +
                               std::to_string(line_number) +
                               ": expected four or five columns");
    }
    grouped[track_id].push_back(point);
  }
  if (shrink_override)
    shrink = *shrink_override;
  if (shrink <= 0)
    throw std::runtime_error("Shrink must be positive");
  std::vector<Track> tracks;
  for (auto &[id, points] : grouped) {
    if (points.size() < 2)
      throw std::runtime_error("track " + std::to_string(id) +
                               " has fewer than two points");
    for (auto &point : points)
      point.z /= shrink;
    tracks.push_back({id, std::move(points)});
  }
  return {tracks, shrink};
}

class ImageCache {
public:
  ImageCache(const Stack &stack, const std::vector<cv::Point2d> &track_points,
             const Config &config)
      : stack_(stack), kernel_(config.gaussian_kernel_px) {
    const int gaussian_radius = kernel_ / 2;
    const int margin = static_cast<int>(std::ceil(
        std::max(config.profile_half_width_um / stack.pixel_size_um(),
                 static_cast<double>(config.focus_window_px)) +
        gaussian_radius + 4));
    const auto [minimum_x, maximum_x] =
        std::minmax_element(track_points.begin(), track_points.end(),
                            [](const auto &left, const auto &right) {
                              return left.x < right.x;
                            });
    const auto [minimum_y, maximum_y] =
        std::minmax_element(track_points.begin(), track_points.end(),
                            [](const auto &left, const auto &right) {
                              return left.y < right.y;
                            });
    x0_ = std::max(0, static_cast<int>(std::floor(minimum_x->x)) - margin);
    y0_ = std::max(0, static_cast<int>(std::floor(minimum_y->y)) - margin);
    const int x1 =
        std::min(stack.width, static_cast<int>(std::ceil(maximum_x->x)) +
                                  margin + 1);
    const int y1 =
        std::min(stack.height, static_cast<int>(std::ceil(maximum_y->y)) +
                                   margin + 1);
    roi_ = {x0_, y0_, x1 - x0_, y1 - y0_};
  }

  const cv::Mat &dog(int frame_index) {
    const auto found = cache_.find(frame_index);
    if (found != cache_.end())
      return found->second;
    cv::Mat image =
        cv::imread(stack_.frames.at(frame_index).path.string(),
                   cv::IMREAD_GRAYSCALE);
    if (image.empty())
      throw std::runtime_error("cannot read " +
                               stack_.frames.at(frame_index).path.string());
    cv::Mat crop = image(roi_);
    cv::Mat background;
    cv::GaussianBlur(crop, background, {kernel_, kernel_}, 0);
    cv::Mat processed;
    cv::subtract(background, crop, processed);
    return cache_.emplace(frame_index, std::move(processed)).first->second;
  }

  cv::Point2d local(cv::Point2d point) const {
    return {point.x - x0_, point.y - y0_};
  }

private:
  const Stack &stack_;
  int kernel_{};
  int x0_{};
  int y0_{};
  cv::Rect roi_;
  std::unordered_map<int, cv::Mat> cache_;
};

double bilinear(const cv::Mat &image, double x, double y) {
  x = std::clamp(x, 0.0, static_cast<double>(image.cols - 1));
  y = std::clamp(y, 0.0, static_cast<double>(image.rows - 1));
  const int x0 = static_cast<int>(std::floor(x));
  const int y0 = static_cast<int>(std::floor(y));
  const int x1 = std::min(x0 + 1, image.cols - 1);
  const int y1 = std::min(y0 + 1, image.rows - 1);
  const double fx = x - x0;
  const double fy = y - y0;
  return (1 - fx) * (1 - fy) * image.at<unsigned char>(y0, x0) +
         fx * (1 - fy) * image.at<unsigned char>(y0, x1) +
         (1 - fx) * fy * image.at<unsigned char>(y1, x0) +
         fx * fy * image.at<unsigned char>(y1, x1);
}

double edge_resolution(double saturation, double sigma) {
  const double peak = std::tanh(saturation);
  const auto radius = [&](double fraction) {
    return sigma * std::sqrt(2.0 * std::log(
                                 saturation /
                                 std::atanh(fraction * peak)));
  };
  return radius(0.10) - radius(0.90);
}

double inflection_width(double saturation, double sigma) {
  const auto equation = [&](double radius) {
    const double u =
        saturation * std::exp(-radius * radius / (2.0 * sigma * sigma));
    return radius * radius * (1.0 - 2.0 * u * std::tanh(u)) - sigma * sigma;
  };
  double low = 0.0;
  double high = 10.0 * sigma;
  for (int iteration = 0; iteration < 100; ++iteration) {
    const double middle = (low + high) / 2.0;
    if (equation(middle) > 0)
      high = middle;
    else
      low = middle;
  }
  return low + high;
}

double median(std::vector<double> values) {
  if (values.empty())
    return std::numeric_limits<double>::quiet_NaN();
  const auto middle = values.begin() + values.size() / 2;
  std::nth_element(values.begin(), middle, values.end());
  if (values.size() % 2)
    return *middle;
  const double upper = *middle;
  return (upper + *std::max_element(values.begin(), middle)) / 2.0;
}

double estimate_noise_sigma(const std::vector<double> &samples) {
  const double center = median(samples);
  std::vector<double> deviations;
  deviations.reserve(samples.size());
  double sum_squares = 0.0;
  for (const double value : samples) {
    deviations.push_back(std::abs(value - center));
    sum_squares += std::pow(value - center, 2);
  }
  const double mad_sigma = 1.4826 * median(deviations);
  const double clipped_rms_sigma =
      std::sqrt(2.0 * sum_squares / samples.size());
  return std::max({mad_sigma, clipped_rms_sigma, 1.0});
}

struct ProfileFit {
  double resolution_nm{};
  double width_nm{};
  double sigma_nm{};
  double contrast{};
  double fit_r2{};
  double fit_nrmse{};
  double reduced_chi2{};
  double fit_p_value{};
  double width_error_nm{};
  double width_relative_error{};
  double noise_sigma{};
};

std::optional<ProfileFit>
fit_profile(const std::vector<double> &coordinates,
            const std::vector<double> &brightness,
            const std::vector<double> &background_samples) {
  const auto [minimum, maximum] =
      std::minmax_element(brightness.begin(), brightness.end());
  const double contrast = *maximum - *minimum;
  if (contrast <= 0)
    return std::nullopt;
  const double noise_sigma = estimate_noise_sigma(background_samples);
  const auto maximum_position =
      std::distance(brightness.begin(),
                    std::max_element(brightness.begin(), brightness.end()));
  std::vector<double> errors(brightness.size(), noise_sigma);
  TGraphErrors graph(static_cast<int>(coordinates.size()), coordinates.data(),
                     brightness.data(), nullptr, errors.data());
  TF1 model("tanh_gaussian",
            "[3]*TMath::TanH([0]*TMath::Exp(-0.5*((x-[1])/[2])^2))",
            coordinates.front(), coordinates.back());
  model.SetParameters(1.0, coordinates.at(maximum_position), 200.0,
                      std::max(1.0, *maximum));
  model.SetParLimits(0, 0.01, 10.0);
  model.SetParLimits(1, coordinates.front(), coordinates.back());
  model.SetParLimits(2, 10.0, 2000.0);
  model.SetParLimits(3, 0.1, 1000.0);
  const TFitResultPtr result = graph.Fit(&model, "QSN");
  if (static_cast<int>(result) != 0)
    return std::nullopt;
  const double saturation = model.GetParameter(0);
  const double sigma = model.GetParameter(2);
  const double width = inflection_width(saturation, sigma);

  const double mean = std::accumulate(brightness.begin(), brightness.end(), 0.0) /
                      brightness.size();
  double ss_res = 0.0;
  double ss_tot = 0.0;
  double chi2_value = 0.0;
  for (std::size_t i = 0; i < brightness.size(); ++i) {
    const double residual = brightness[i] - model.Eval(coordinates[i]);
    ss_res += residual * residual;
    ss_tot += std::pow(brightness[i] - mean, 2);
    chi2_value += std::pow(residual / noise_sigma, 2);
  }
  const double rmse = std::sqrt(ss_res / brightness.size());
  const double fit_r2 = ss_tot > 0.0
                            ? 1.0 - ss_res / ss_tot
                            : std::numeric_limits<double>::quiet_NaN();
  const int dof = static_cast<int>(brightness.size()) - model.GetNpar();
  const double reduced_chi2 = dof > 0
                                  ? chi2_value / dof
                                  : std::numeric_limits<double>::quiet_NaN();
  const double p_value = dof > 0
                             ? ROOT::Math::chisquared_cdf_c(chi2_value, dof)
                             : std::numeric_limits<double>::quiet_NaN();

  const double ds = std::max(std::abs(saturation) * 1e-5, 1e-6);
  const double d_sigma = std::max(std::abs(sigma) * 1e-5, 1e-3);
  const double dw_ds = (inflection_width(saturation + ds, sigma) -
                        inflection_width(saturation - ds, sigma)) /
                       (2.0 * ds);
  const double dw_dsigma =
      (inflection_width(saturation, sigma + d_sigma) -
       inflection_width(saturation, sigma - d_sigma)) /
      (2.0 * d_sigma);
  const double width_variance =
      dw_ds * dw_ds * result->CovMatrix(0, 0) +
      2.0 * dw_ds * dw_dsigma * result->CovMatrix(0, 2) +
      dw_dsigma * dw_dsigma * result->CovMatrix(2, 2);
  const double width_error =
      std::isfinite(width_variance) && width_variance >= 0.0
          ? std::sqrt(width_variance)
          : std::numeric_limits<double>::infinity();

  return ProfileFit{edge_resolution(saturation, sigma),
                    width,
                    sigma,
                    contrast,
                    fit_r2,
                    rmse / contrast,
                    reduced_chi2,
                    p_value,
                    width_error,
                    width > 0.0 && std::isfinite(width_error)
                        ? width_error / width
                        : std::numeric_limits<double>::infinity(),
                    noise_sigma};
}

std::vector<ThicknessRecord>
measure_track(const Stack &stack, const Track &track, const Config &config) {
  const Polyline polyline(track);
  const double length_um = polyline.length_um();
  if (length_um <= 2.0 * config.endpoint_margin_um)
    throw std::runtime_error("track " + std::to_string(track.id) +
                             " is too short for the endpoint margin");
  std::vector<cv::Point2d> track_pixels;
  for (const auto &point : polyline.points())
    track_pixels.push_back(stack.stage_to_pixel(point.x, point.y));
  ImageCache cache(stack, track_pixels, config);
  std::vector<ThicknessRecord> records;

  for (double distance = config.endpoint_margin_um;
       distance <= length_um - config.endpoint_margin_um + 1e-9;
       distance += config.spacing_um) {
    const auto sampled_track = polyline.sample(distance);
    const Point &point = sampled_track.point;
    const cv::Point2d &direction = sampled_track.direction_xy;
    const cv::Point2d perpendicular(-direction.y, direction.x);
    const cv::Point2d point_local =
        cache.local(stack.stage_to_pixel(point.x, point.y));
    int center_index = 0;
    double nearest = std::numeric_limits<double>::infinity();
    for (int i = 0; i < static_cast<int>(stack.frames.size()); ++i) {
      const double difference = std::abs(stack.frames[i].z - point.z);
      if (difference < nearest) {
        nearest = difference;
        center_index = i;
      }
    }
    const int low = std::max(0, center_index - config.focus_search_frames);
    const int high = std::min(static_cast<int>(stack.frames.size()),
                              center_index + config.focus_search_frames + 1);
    int best_index = -1;
    double best_focus = -std::numeric_limits<double>::infinity();
    for (int frame_index = low; frame_index < high; ++frame_index) {
      const cv::Mat &dog = cache.dog(frame_index);
      const int x = static_cast<int>(std::round(point_local.x));
      const int y = static_cast<int>(std::round(point_local.y));
      const int radius = config.focus_window_px;
      const int x0 = std::max(0, x - radius);
      const int y0 = std::max(0, y - radius);
      const int x1 = std::min(dog.cols, x + radius);
      const int y1 = std::min(dog.rows, y + radius);
      const double score =
          cv::sum(dog(cv::Rect(x0, y0, x1 - x0, y1 - y0)))[0];
      if (score > best_focus) {
        best_focus = score;
        best_index = frame_index;
      }
    }

    std::vector<double> coordinates;
    std::vector<double> brightness;
    std::vector<double> background_samples;
    const double step_um = stack.pixel_size_um();
    std::vector<double> offsets;
    for (double offset = -config.profile_half_width_um;
         offset <= config.profile_half_width_um + 0.5 * step_um;
         offset += step_um)
      offsets.push_back(offset);
    const std::size_t tail_size =
        std::max<std::size_t>(2, static_cast<std::size_t>(
                                     std::ceil(offsets.size() * 0.25)));
    for (std::size_t offset_index = 0; offset_index < offsets.size();
         ++offset_index) {
      const double offset = offsets[offset_index];
      const cv::Point2d sample_global = stack.stage_to_pixel(
          point.x + perpendicular.x * offset / 1000.0,
          point.y + perpendicular.y * offset / 1000.0);
      const cv::Point2d sample_local = cache.local(sample_global);
      coordinates.push_back(offset * 1000.0);
      brightness.push_back(
          bilinear(cache.dog(best_index), sample_local.x, sample_local.y));
      if (offset_index < tail_size || offset_index + tail_size >= offsets.size()) {
        for (const double longitudinal : {-0.5, -0.25, 0.25, 0.5}) {
          const cv::Point2d background_global = stack.stage_to_pixel(
              point.x + (perpendicular.x * offset + direction.x * longitudinal) /
                            1000.0,
              point.y + (perpendicular.y * offset + direction.y * longitudinal) /
                            1000.0);
          const cv::Point2d background_local = cache.local(background_global);
          background_samples.push_back(bilinear(cache.dog(best_index),
                                                background_local.x,
                                                background_local.y));
        }
      }
    }
    const auto [minimum, maximum] =
        std::minmax_element(brightness.begin(), brightness.end());
    if (*maximum - *minimum < config.minimum_contrast)
      continue;
    const auto fit = fit_profile(coordinates, brightness, background_samples);
    if (fit)
      records.push_back({track.id,
                         distance,
                         fit->resolution_nm,
                         fit->width_nm,
                         fit->sigma_nm,
                         fit->contrast,
                         fit->fit_r2,
                         fit->fit_nrmse,
                         fit->reduced_chi2,
                         fit->fit_p_value,
                         fit->width_error_nm,
                         fit->width_relative_error,
                         fit->noise_sigma});
  }
  return records;
}

int main(int argc, char **argv) {
  try {
    fs::path json_path;
    fs::path track_path;
    fs::path output;
    std::set<int> selected_tracks;
    std::optional<double> shrink_override;
    Config config;
    for (int i = 1; i < argc; ++i) {
      const std::string argument = argv[i];
      auto next = [&]() -> std::string {
        if (++i >= argc)
          throw std::runtime_error("missing value after " + argument);
        return argv[i];
      };
      if (argument == "-o" || argument == "--output")
        output = next();
      else if (argument == "--track-id")
        selected_tracks.insert(std::stoi(next()));
      else if (argument == "--shrink")
        shrink_override = std::stod(next());
      else if (argument == "--spacing-um")
        config.spacing_um = std::stod(next());
      else if (argument == "--endpoint-margin-um")
        config.endpoint_margin_um = std::stod(next());
      else if (argument == "--profile-half-width-um")
        config.profile_half_width_um = std::stod(next());
      else if (argument == "--focus-search-frames")
        config.focus_search_frames = std::stoi(next());
      else if (argument == "--minimum-contrast")
        config.minimum_contrast = std::stod(next());
      else if (json_path.empty())
        json_path = argument;
      else if (track_path.empty())
        track_path = argument;
      else
        throw std::runtime_error("unexpected argument: " + argument);
    }
    if (json_path.empty() || track_path.empty()) {
      std::cerr << "Usage: track_thickness_root IMAGE_JSON TRACKS [-o OUTPUT] "
                   "[--track-id ID]\n";
      return 2;
    }
    if (output.empty())
      output = track_path.parent_path() / "track_thickness.txt";
    const Stack stack = load_stack(json_path);
    auto [tracks, shrink] = load_tracks(track_path, shrink_override);
    std::vector<ThicknessRecord> records;
    int requested = 0;
    for (const auto &track : tracks) {
      if (!selected_tracks.empty() && !selected_tracks.count(track.id))
        continue;
      ++requested;
      auto measured = measure_track(stack, track, config);
      records.insert(records.end(), measured.begin(), measured.end());
    }
    thickness::write_thickness(
        output, records,
        {"image_json: " + fs::absolute(json_path).string(),
         "tracks: " + fs::absolute(track_path).string(),
         "input_shrink: " + std::to_string(shrink),
         "multi-point policy: 3D polyline with local transverse profiles",
         "fit noise model: neighboring-profile tails (MAD/clipped RMS)"});
    std::set<int> measured_ids;
    for (const auto &row : records)
      measured_ids.insert(row.track_id);
    std::cout << "Wrote " << records.size() << " measurements from "
              << measured_ids.size() << '/' << requested << " tracks to "
              << output << '\n';
  } catch (const std::exception &error) {
    std::cerr << "error: " << error.what() << '\n';
    return 1;
  }
  return 0;
}
