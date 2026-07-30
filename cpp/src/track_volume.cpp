#include "analysis_io.hpp"

#include <iostream>

namespace fs = std::filesystem;

int main(int argc, char **argv) {
  try {
    fs::path input;
    fs::path output;
    double maximum_width_nm = 800.0;
    for (int i = 1; i < argc; ++i) {
      const std::string argument = argv[i];
      if ((argument == "-o" || argument == "--output") && i + 1 < argc)
        output = argv[++i];
      else if (argument == "--maximum-width-nm" && i + 1 < argc)
        maximum_width_nm = std::stod(argv[++i]);
      else if (input.empty())
        input = argument;
      else
        throw std::runtime_error("unexpected argument: " + argument);
    }
    if (input.empty() || output.empty()) {
      std::cerr << "Usage: track_volume_root INPUT -o OUTPUT "
                   "[--maximum-width-nm 800]\n";
      return 2;
    }
    const auto source = thickness::read_thickness(input);
    const auto volumes =
        thickness::calculate_volumes(source, maximum_width_nm);
    thickness::write_volumes(output, volumes);
    std::cout << "Wrote " << volumes.size() << " accepted volume points from "
              << source.size() << " measurements to " << output << '\n';
  } catch (const std::exception &error) {
    std::cerr << "error: " << error.what() << '\n';
    return 1;
  }
  return 0;
}
