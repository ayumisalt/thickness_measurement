#include "analysis_io.hpp"

#include <iostream>
#include <map>
#include <set>

namespace fs = std::filesystem;
using thickness::ThicknessRecord;

int main(int argc, char **argv) {
  try {
    std::vector<fs::path> inputs;
    fs::path output;
    bool renumber = true;
    for (int i = 1; i < argc; ++i) {
      const std::string argument = argv[i];
      if ((argument == "-o" || argument == "--output") && i + 1 < argc)
        output = argv[++i];
      else if (argument == "--keep-track-ids")
        renumber = false;
      else
        inputs.emplace_back(argument);
    }
    if (inputs.empty() || output.empty()) {
      std::cerr << "Usage: summarize_result_root INPUT... -o OUTPUT "
                   "[--keep-track-ids]\n";
      return 2;
    }

    std::vector<ThicknessRecord> combined;
    std::vector<std::string> comments;
    int next_track_id = 1;
    for (const auto &input : inputs) {
      const auto records = thickness::read_thickness(input);
      std::map<int, int> mapping;
      for (const auto &row : records) {
        if (!mapping.count(row.track_id)) {
          mapping[row.track_id] = renumber ? next_track_id++ : row.track_id;
          comments.push_back("source_map: " +
                             std::to_string(mapping[row.track_id]) + " <- " +
                             fs::absolute(input).string() + " track " +
                             std::to_string(row.track_id));
        }
        auto copy = row;
        copy.track_id = mapping.at(row.track_id);
        combined.push_back(copy);
      }
    }
    thickness::write_thickness(output, combined, comments);
    std::cout << "Combined " << combined.size() << " rows from " << inputs.size()
              << " files into " << output << '\n';
  } catch (const std::exception &error) {
    std::cerr << "error: " << error.what() << '\n';
    return 1;
  }
  return 0;
}
