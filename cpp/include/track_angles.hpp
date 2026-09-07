#pragma once

#include "analysis_io.hpp"
#include <set>

namespace thickness {

inline double folded_theta(double theta) {
  if (!std::isfinite(theta) || theta < 0 || theta > 180)
    throw std::runtime_error("theta must be finite and between 0 and 180 degrees");
  return std::min(theta, 180.0 - theta);
}

inline std::map<int, double> read_angles(const std::filesystem::path &path) {
  std::ifstream stream(path);
  if (!stream)
    throw std::runtime_error("cannot open angle table: " + path.string());
  std::map<int, double> result;
  std::string line;
  while (std::getline(stream, line)) {
    const auto start = line.find_first_not_of(" \t\r\n");
    if (start == std::string::npos || line[start] == '#')
      continue;
    std::istringstream row(line);
    std::string id_text, theta_text;
    if (!(row >> id_text >> theta_text))
      throw std::runtime_error("invalid angle row: " + line);
    std::size_t id_end = 0, theta_end = 0;
    const int id = std::stoi(id_text, &id_end);
    const double theta = std::stod(theta_text, &theta_end);
    if (id_end != id_text.size() || theta_end != theta_text.size())
      throw std::runtime_error("invalid angle row: " + line);
    folded_theta(theta);
    if (!result.emplace(id, theta).second)
      throw std::runtime_error("duplicate angle track " + std::to_string(id));
  }
  return result;
}

inline std::pair<std::set<int>, double> select_reference_ids(
    const std::set<int> &reference_ids, const std::map<int, double> &reference_angles,
    const std::set<int> &candidate_ids, const std::map<int, double> &candidate_angles,
    double window) {
  if (!std::isfinite(window) || window < 0 || window > 90)
    throw std::runtime_error("theta window must be finite and between 0 and 90 degrees");
  if (candidate_ids.size() != 1)
    throw std::runtime_error("theta matching requires exactly one candidate track");
  const int candidate_id = *candidate_ids.begin();
  if (!candidate_angles.count(candidate_id))
    throw std::runtime_error("missing candidate angle");
  const double center = folded_theta(candidate_angles.at(candidate_id));
  std::set<int> selected;
  for (int id : reference_ids) {
    if (!reference_angles.count(id))
      throw std::runtime_error("missing reference angle for track " + std::to_string(id));
    if (std::abs(folded_theta(reference_angles.at(id)) - center) <= window + 1e-10)
      selected.insert(id);
  }
  return {selected, center};
}

} // namespace thickness
