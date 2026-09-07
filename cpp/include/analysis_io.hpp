#pragma once

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iterator>
#include <map>
#include <limits>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace thickness {

struct ThicknessRecord {
  int track_id{};
  double distance_um{};
  double resolution_nm{};
  double width_nm{};
  double sigma_nm{};
  double contrast{std::numeric_limits<double>::quiet_NaN()};
  double fit_r2{std::numeric_limits<double>::quiet_NaN()};
  double fit_nrmse{std::numeric_limits<double>::quiet_NaN()};
  double reduced_chi2{std::numeric_limits<double>::quiet_NaN()};
  double fit_p_value{std::numeric_limits<double>::quiet_NaN()};
  double width_error_nm{std::numeric_limits<double>::quiet_NaN()};
  double width_relative_error{std::numeric_limits<double>::quiet_NaN()};
  double noise_sigma{std::numeric_limits<double>::quiet_NaN()};
  double theta_deg{std::numeric_limits<double>::quiet_NaN()};
  double local_theta_deg{std::numeric_limits<double>::quiet_NaN()};
};

struct QualityCuts {
  std::optional<double> minimum_contrast;
  std::optional<double> minimum_fit_r2;
  std::optional<double> maximum_fit_nrmse;
  std::optional<double> maximum_reduced_chi2;
  std::optional<double> minimum_fit_p_value;
  std::optional<double> maximum_width_error_nm;
  std::optional<double> maximum_width_relative_error;
  std::optional<double> maximum_width_nm;
  std::optional<double> minimum_theta_deg;
  std::optional<double> maximum_theta_deg;

  bool requested() const {
    return minimum_contrast || minimum_fit_r2 || maximum_fit_nrmse ||
           maximum_reduced_chi2 || minimum_fit_p_value ||
           maximum_width_error_nm || maximum_width_relative_error ||
           maximum_width_nm || minimum_theta_deg || maximum_theta_deg;
  }
};

inline bool is_quality_cut_option(const std::string &argument) {
  return argument == "--minimum-contrast" ||
         argument == "--minimum-fit-r2" ||
         argument == "--maximum-fit-nrmse" ||
         argument == "--maximum-reduced-chi2" ||
         argument == "--minimum-fit-p-value" ||
         argument == "--maximum-width-error-nm" ||
         argument == "--maximum-width-relative-error" ||
         argument == "--maximum-width-nm" || argument == "--minimum-theta-deg" ||
         argument == "--maximum-theta-deg";
}

inline void set_quality_cut(QualityCuts &cuts, const std::string &argument,
                            const std::string &text) {
  const double value = std::stod(text);
  if (argument == "--minimum-contrast")
    cuts.minimum_contrast = value;
  else if (argument == "--minimum-fit-r2")
    cuts.minimum_fit_r2 = value;
  else if (argument == "--maximum-fit-nrmse")
    cuts.maximum_fit_nrmse = value;
  else if (argument == "--maximum-reduced-chi2")
    cuts.maximum_reduced_chi2 = value;
  else if (argument == "--minimum-fit-p-value")
    cuts.minimum_fit_p_value = value;
  else if (argument == "--maximum-width-error-nm")
    cuts.maximum_width_error_nm = value;
  else if (argument == "--maximum-width-relative-error")
    cuts.maximum_width_relative_error = value;
  else if (argument == "--maximum-width-nm")
    cuts.maximum_width_nm = value;
  else if (argument == "--minimum-theta-deg")
    cuts.minimum_theta_deg = value;
  else if (argument == "--maximum-theta-deg")
    cuts.maximum_theta_deg = value;
  else
    throw std::runtime_error("unknown quality-cut option: " + argument);
}

inline void validate_quality_cuts(const QualityCuts &cuts) {
  for (const auto &value : {cuts.minimum_theta_deg, cuts.maximum_theta_deg})
    if (value && (!std::isfinite(*value) || *value < 0 || *value > 90))
      throw std::runtime_error("theta limits must be finite and between 0 and 90 degrees");
  if (cuts.minimum_theta_deg && cuts.maximum_theta_deg && *cuts.minimum_theta_deg > *cuts.maximum_theta_deg)
    throw std::runtime_error("minimum theta cannot exceed maximum theta");
  const auto require_nonnegative = [](const std::optional<double> &value,
                                      const std::string &name) {
    if (value && *value < 0.0)
      throw std::runtime_error(name + " must be non-negative");
  };
  require_nonnegative(cuts.minimum_contrast, "--minimum-contrast");
  require_nonnegative(cuts.maximum_fit_nrmse, "--maximum-fit-nrmse");
  require_nonnegative(cuts.maximum_reduced_chi2, "--maximum-reduced-chi2");
  require_nonnegative(cuts.maximum_width_error_nm,
                      "--maximum-width-error-nm");
  require_nonnegative(cuts.maximum_width_relative_error,
                      "--maximum-width-relative-error");
  require_nonnegative(cuts.maximum_width_nm, "--maximum-width-nm");
  if (cuts.minimum_fit_r2 && *cuts.minimum_fit_r2 > 1.0)
    throw std::runtime_error("--minimum-fit-r2 cannot exceed 1");
  if (cuts.minimum_fit_p_value &&
      (*cuts.minimum_fit_p_value < 0.0 || *cuts.minimum_fit_p_value > 1.0))
    throw std::runtime_error("--minimum-fit-p-value must be between 0 and 1");
}

struct VolumeRecord {
  int track_id{};
  double range_um{};
  double volume_um3{};
};

inline std::vector<ThicknessRecord>
read_thickness(const std::filesystem::path &path) {
  std::ifstream input(path);
  if (!input)
    throw std::runtime_error("cannot open " + path.string());
  std::vector<ThicknessRecord> records;
  std::string line;
  int line_number = 0;
  while (std::getline(input, line)) {
    ++line_number;
    const auto first = line.find_first_not_of(" \t\r\n");
    if (first == std::string::npos || line[first] == '#')
      continue;
    std::istringstream parser(line);
    std::vector<double> values;
    std::string token;
    while (parser >> token)
      values.push_back(std::stod(token));
    if (values.size() < 5) {
      throw std::runtime_error(path.string() + ":" +
                               std::to_string(line_number) +
                               ": expected at least five columns");
    }
    ThicknessRecord row;
    row.track_id = static_cast<int>(values[0]);
    row.distance_um = values[1];
    row.resolution_nm = values[2];
    row.width_nm = values[3];
    row.sigma_nm = values[4];
    double *optional_fields[] = {
        &row.contrast,          &row.fit_r2,
        &row.fit_nrmse,         &row.reduced_chi2,
        &row.fit_p_value,       &row.width_error_nm,
        &row.width_relative_error, &row.noise_sigma, &row.theta_deg, &row.local_theta_deg};
    for (std::size_t i = 0; i < std::size(optional_fields) && i + 5 < values.size(); ++i)
      *optional_fields[i] = values[i + 5];
    records.push_back(row);
  }
  return records;
}

inline void
write_thickness(const std::filesystem::path &path,
                const std::vector<ThicknessRecord> &records,
                const std::vector<std::string> &comments = {}) {
  if (path.has_parent_path())
    std::filesystem::create_directories(path.parent_path());
  std::ofstream output(path);
  if (!output)
    throw std::runtime_error("cannot write " + path.string());
  output << "# columns: track_id distance_um resolution_nm width_nm sigma_nm "
            "contrast fit_r2 fit_nrmse reduced_chi2 fit_p_value "
            "width_error_nm width_relative_error noise_sigma theta_deg local_theta_deg\n";
  output << "# theta convention: acquisition z; polar 0-180 deg; endpoint theta and local segment theta; nan if unavailable\n";
  for (const auto &comment : comments)
    output << "# " << comment << '\n';
  for (const auto &row : records) {
    output << row.track_id << ' ' << std::fixed << std::setprecision(6)
           << row.distance_um << ' ' << row.resolution_nm << ' ' << row.width_nm
           << ' ' << row.sigma_nm << ' ' << row.contrast << ' '
           << std::setprecision(9) << row.fit_r2 << ' ' << row.fit_nrmse << ' '
           << row.reduced_chi2 << ' ' << std::scientific << row.fit_p_value
           << std::fixed << std::setprecision(6) << ' ' << row.width_error_nm
           << ' ' << std::setprecision(9) << row.width_relative_error << ' '
           << std::setprecision(6) << row.noise_sigma << ' '
           << std::setprecision(9) << row.theta_deg << ' ' << row.local_theta_deg << '\n';
  }
}

inline bool passes_quality(const ThicknessRecord &row, const QualityCuts &cuts) {
  const auto minimum = [](double value, const std::optional<double> &limit) {
    return !limit || (std::isfinite(value) && value >= *limit);
  };
  const auto maximum = [](double value, const std::optional<double> &limit) {
    return !limit || (std::isfinite(value) && value <= *limit);
  };
  return std::isfinite(row.width_nm) && row.width_nm > 0.0 &&
         minimum(row.contrast, cuts.minimum_contrast) &&
         minimum(row.fit_r2, cuts.minimum_fit_r2) &&
         maximum(row.fit_nrmse, cuts.maximum_fit_nrmse) &&
         maximum(row.reduced_chi2, cuts.maximum_reduced_chi2) &&
         minimum(row.fit_p_value, cuts.minimum_fit_p_value) &&
         maximum(row.width_error_nm, cuts.maximum_width_error_nm) &&
         maximum(row.width_relative_error,
                 cuts.maximum_width_relative_error) &&
         maximum(row.width_nm, cuts.maximum_width_nm) &&
         minimum(std::min(row.theta_deg, 180 - row.theta_deg), cuts.minimum_theta_deg) &&
         maximum(std::min(row.theta_deg, 180 - row.theta_deg), cuts.maximum_theta_deg);
}

inline std::map<int, double> embedded_angles(const std::vector<ThicknessRecord> &records) {
  std::map<int, double> result;
  for (const auto &row : records) {
    if (!std::isfinite(row.theta_deg) || row.theta_deg < 0 || row.theta_deg > 180)
      throw std::runtime_error("missing/invalid embedded theta; regenerate thickness or provide an angle table");
    if (result.count(row.track_id) && std::abs(result.at(row.track_id) - row.theta_deg) > 1e-7)
      throw std::runtime_error("inconsistent embedded theta for track " + std::to_string(row.track_id));
    result[row.track_id] = row.theta_deg;
  }
  return result;
}

inline std::vector<VolumeRecord>
calculate_volumes(std::vector<ThicknessRecord> records,
                  const QualityCuts &cuts = {}) {
  if (cuts.minimum_theta_deg || cuts.maximum_theta_deg)
    embedded_angles(records);
  std::map<int, std::vector<ThicknessRecord>> grouped;
  for (const auto &row : records)
    grouped[row.track_id].push_back(row);
  std::vector<VolumeRecord> result;
  constexpr double pi = 3.14159265358979323846;
  for (auto &[track_id, rows] : grouped) {
    std::sort(rows.begin(), rows.end(), [](const auto &left, const auto &right) {
      return left.distance_um < right.distance_um;
    });
    if (!cuts.requested()) {
      double previous = 0.0;
      double volume = 0.0;
      for (const auto &row : rows) {
        const double interval = row.distance_um - previous;
        if (interval < 0)
          throw std::runtime_error("non-monotonic distance for track " +
                                   std::to_string(track_id));
        previous = row.distance_um;
        if (!std::isfinite(row.width_nm) || row.width_nm <= 0.0)
          continue;
        const double radius_um = row.width_nm / 2000.0;
        volume += pi * radius_um * radius_um * interval;
        result.push_back({track_id, row.distance_um, volume});
      }
      continue;
    }

    std::vector<std::size_t> accepted;
    for (std::size_t i = 0; i < rows.size(); ++i)
      if (passes_quality(rows[i], cuts))
        accepted.push_back(i);

    if (accepted.size() < 2)
      continue;

    const std::size_t first = accepted.front();
    const std::size_t last = accepted.back();
    std::size_t bracket = 0;
    double previous = 0.0;
    double volume = 0.0;
    for (std::size_t i = first; i <= last; ++i) {
      const auto &row = rows[i];
      const double interval = row.distance_um - previous;
      if (interval < 0)
        throw std::runtime_error("non-monotonic distance for track " +
                                 std::to_string(track_id));
      previous = row.distance_um;

      while (bracket + 1 < accepted.size() && accepted[bracket + 1] < i)
        ++bracket;
      double width = row.width_nm;
      if (!passes_quality(row, cuts)) {
        const auto &left = rows[accepted[bracket]];
        const auto &right = rows[accepted[bracket + 1]];
        const double span = right.distance_um - left.distance_um;
        const double fraction = span > 0.0
                                    ? (row.distance_um - left.distance_um) / span
                                    : 0.0;
        width = left.width_nm + fraction * (right.width_nm - left.width_nm);
      }
      const double radius_um = width / 2000.0;
      volume += pi * radius_um * radius_um * interval;
      result.push_back({track_id, row.distance_um, volume});
    }
  }
  return result;
}

inline void write_volumes(const std::filesystem::path &path,
                          const std::vector<VolumeRecord> &records) {
  if (path.has_parent_path())
    std::filesystem::create_directories(path.parent_path());
  std::ofstream output(path);
  if (!output)
    throw std::runtime_error("cannot write " + path.string());
  output << "# columns: track_id range_um cumulative_volume_um3\n";
  output << std::fixed << std::setprecision(9);
  for (const auto &row : records)
    output << row.track_id << ' ' << row.range_um << ' ' << row.volume_um3
           << '\n';
}

inline std::vector<VolumeRecord>
read_volumes(const std::filesystem::path &path) {
  std::ifstream input(path);
  if (!input)
    throw std::runtime_error("cannot open " + path.string());
  std::vector<VolumeRecord> records;
  std::string line;
  int line_number = 0;
  while (std::getline(input, line)) {
    ++line_number;
    const auto first = line.find_first_not_of(" \t\r\n");
    if (first == std::string::npos || line[first] == '#')
      continue;
    std::istringstream parser(line);
    std::vector<double> values;
    double value{};
    while (parser >> value)
      values.push_back(value);
    if (values.size() >= 3)
      records.push_back(
          {static_cast<int>(values[0]), values[1], values[2]});
    else if (values.size() == 2)
      records.push_back({1, values[0], values[1]});
    else
      throw std::runtime_error(path.string() + ":" +
                               std::to_string(line_number) +
                               ": expected two or three columns");
  }
  return records;
}

} // namespace thickness
