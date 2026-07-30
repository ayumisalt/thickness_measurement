#pragma once

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <map>
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
};

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
    ThicknessRecord row;
    std::istringstream parser(line);
    if (!(parser >> row.track_id >> row.distance_um >> row.resolution_nm >>
          row.width_nm >> row.sigma_nm)) {
      throw std::runtime_error(path.string() + ":" +
                               std::to_string(line_number) +
                               ": expected five columns");
    }
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
  output << "# columns: track_id distance_um resolution_nm width_nm sigma_nm\n";
  for (const auto &comment : comments)
    output << "# " << comment << '\n';
  output << std::fixed << std::setprecision(6);
  for (const auto &row : records) {
    output << row.track_id << ' ' << row.distance_um << ' ' << row.resolution_nm
           << ' ' << row.width_nm << ' ' << row.sigma_nm << '\n';
  }
}

inline std::vector<VolumeRecord>
calculate_volumes(std::vector<ThicknessRecord> records,
                  double maximum_width_nm = 800.0) {
  std::map<int, std::vector<ThicknessRecord>> grouped;
  for (const auto &row : records)
    grouped[row.track_id].push_back(row);
  std::vector<VolumeRecord> result;
  constexpr double pi = 3.14159265358979323846;
  for (auto &[track_id, rows] : grouped) {
    std::sort(rows.begin(), rows.end(), [](const auto &left, const auto &right) {
      return left.distance_um < right.distance_um;
    });
    double previous = 0.0;
    double volume = 0.0;
    for (const auto &row : rows) {
      const double interval = row.distance_um - previous;
      if (interval < 0)
        throw std::runtime_error("non-monotonic distance for track " +
                                 std::to_string(track_id));
      previous = row.distance_um;
      if (!(row.width_nm > 0.0 && row.width_nm <= maximum_width_nm))
        continue;
      const double radius_um = row.width_nm / 2000.0;
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
