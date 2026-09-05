#include "analysis_io.hpp"

#include <iostream>

namespace fs = std::filesystem;

int main(int argc, char **argv) {
  try {
    fs::path input;
    fs::path output;
    thickness::QualityCuts cuts;
    for (int i = 1; i < argc; ++i) {
      const std::string argument = argv[i];
      if ((argument == "-o" || argument == "--output") && i + 1 < argc)
        output = argv[++i];
      else if (thickness::is_quality_cut_option(argument) && i + 1 < argc)
        thickness::set_quality_cut(cuts, argument, argv[++i]);
      else if (input.empty())
        input = argument;
      else
        throw std::runtime_error("unexpected argument: " + argument);
    }
    if (input.empty() || output.empty()) {
      std::cerr << "Usage: track_volume_root INPUT -o OUTPUT "
                   "[fit-quality cuts]\n";
      return 2;
    }
    thickness::validate_quality_cuts(cuts);
    const auto source = thickness::read_thickness(input);
    const auto volumes = thickness::calculate_volumes(source, cuts);
    thickness::write_volumes(output, volumes);
    std::cout << "Wrote " << volumes.size() << " volume points from "
              << source.size() << " measurements to " << output << '\n';
  } catch (const std::exception &error) {
    std::cerr << "error: " << error.what() << '\n';
    return 1;
  }
  return 0;
}
