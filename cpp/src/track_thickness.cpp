#include "analysis_io.hpp"

#include <TF1.h>
#include <TFitResultPtr.h>
#include <TGraph.h>

#include <nlohmann/json.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <array>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
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
  ImageCache(const Stack &stack, cv::Point2d start, cv::Point2d end,
             const Config &config)
      : stack_(stack), kernel_(config.gaussian_kernel_px) {
    const int gaussian_radius = kernel_ / 2;
    const int margin = static_cast<int>(std::ceil(
        std::max(config.profile_half_width_um / stack.pixel_size_um(),
                 static_cast<double>(config.focus_window_px)) +
        gaussian_radius + 4));
    x0_ = std::max(0, static_cast<int>(std::floor(std::min(start.x, end.x))) -
                          margin);
    y0_ = std::max(0, static_cast<int>(std::floor(std::min(start.y, end.y))) -
                          margin);
    const int x1 =
        std::min(stack.width,
                 static_cast<int>(std::ceil(std::max(start.x, end.x))) +
                     margin + 1);
    const int y1 =
        std::min(stack.height,
                 static_cast<int>(std::ceil(std::max(start.y, end.y))) +
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

std::optional<std::array<double, 3>>
fit_profile(const std::vector<double> &coordinates,
            const std::vector<double> &brightness) {
  const auto [minimum, maximum] =
      std::minmax_element(brightness.begin(), brightness.end());
  if (*maximum - *minimum <= 0)
    return std::nullopt;
  const auto maximum_position =
      std::distance(brightness.begin(),
                    std::max_element(brightness.begin(), brightness.end()));
  TGraph graph(static_cast<int>(coordinates.size()), coordinates.data(),
               brightness.data());
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
  return std::array<double, 3>{edge_resolution(saturation, sigma),
                               inflection_width(saturation, sigma), sigma};
}

std::vector<ThicknessRecord>
measure_track(const Stack &stack, const Track &track, const Config &config) {
  const Point &start = track.points.front();
  const Point &end = track.points.back();
  const double dx = end.x - start.x;
  const double dy = end.y - start.y;
  const double length_mm = std::hypot(dx, dy);
  const double length_um = length_mm * 1000.0;
  if (length_um <= 2.0 * config.endpoint_margin_um)
    throw std::runtime_error("track " + std::to_string(track.id) +
                             " is too short for the endpoint margin");
  const cv::Point2d direction(dx / length_mm, dy / length_mm);
  const cv::Point2d perpendicular(-direction.y, direction.x);
  ImageCache cache(stack, stack.stage_to_pixel(start.x, start.y),
                   stack.stage_to_pixel(end.x, end.y), config);
  std::vector<ThicknessRecord> records;

  for (double distance = config.endpoint_margin_um;
       distance <= length_um - config.endpoint_margin_um + 1e-9;
       distance += config.spacing_um) {
    const double fraction = distance / length_um;
    const Point point{start.x + fraction * dx, start.y + fraction * dy,
                      start.z + fraction * (end.z - start.z)};
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
    const double step_um = stack.pixel_size_um();
    for (double offset = -config.profile_half_width_um;
         offset <= config.profile_half_width_um + 0.5 * step_um;
         offset += step_um) {
      const cv::Point2d sample_global = stack.stage_to_pixel(
          point.x + perpendicular.x * offset / 1000.0,
          point.y + perpendicular.y * offset / 1000.0);
      const cv::Point2d sample_local = cache.local(sample_global);
      coordinates.push_back(offset * 1000.0);
      brightness.push_back(
          bilinear(cache.dog(best_index), sample_local.x, sample_local.y));
    }
    const auto [minimum, maximum] =
        std::minmax_element(brightness.begin(), brightness.end());
    if (*maximum - *minimum < config.minimum_contrast)
      continue;
    const auto fit = fit_profile(coordinates, brightness);
    if (fit)
      records.push_back(
          {track.id, distance, (*fit)[0], (*fit)[1], (*fit)[2]});
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
         "multi-point policy: first and last point are endpoints"});
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
