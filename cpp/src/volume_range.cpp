#include "analysis_io.hpp"

#include <TCanvas.h>
#include <TAxis.h>
#include <TGraph.h>
#include <TGraphErrors.h>
#include <TLegend.h>
#include <TMultiGraph.h>
#include <TROOT.h>
#include <TStyle.h>

#include <cmath>
#include <array>
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <tuple>

namespace fs = std::filesystem;
using thickness::VolumeRecord;

std::vector<VolumeRecord>
load_analysis(const fs::path &path, const std::string &input_type,
              const thickness::QualityCuts &cuts) {
  if (input_type == "volume")
    return thickness::read_volumes(path);
  if (input_type == "thickness")
    return thickness::calculate_volumes(thickness::read_thickness(path), cuts);
  throw std::runtime_error("unknown input type: " + input_type);
}

struct Fit {
  double slope{};
  double error{};
};

Fit fit_origin(const std::vector<double> &x, const std::vector<double> &y,
               const std::vector<double> *sigma = nullptr) {
  if (x.empty())
    throw std::runtime_error("no points to fit");
  double numerator = 0.0;
  double denominator = 0.0;
  std::vector<double> weights(x.size(), 1.0);
  if (sigma) {
    double fallback = 1.0;
    std::vector<double> positive_errors;
    for (double value : *sigma)
      if (value > 0)
        positive_errors.push_back(value);
    if (!positive_errors.empty()) {
      const auto middle = positive_errors.begin() + positive_errors.size() / 2;
      std::nth_element(positive_errors.begin(), middle, positive_errors.end());
      fallback = *middle;
      if (positive_errors.size() % 2 == 0) {
        const double lower =
            *std::max_element(positive_errors.begin(), middle);
        fallback = (lower + fallback) / 2.0;
      }
    }
    for (std::size_t i = 0; i < x.size(); ++i) {
      const double error = sigma->at(i) > 0 ? sigma->at(i) : fallback;
      weights[i] = 1.0 / (error * error);
    }
  }
  for (std::size_t i = 0; i < x.size(); ++i) {
    numerator += weights[i] * x[i] * y[i];
    denominator += weights[i] * x[i] * x[i];
  }
  if (denominator == 0)
    throw std::runtime_error("all fitted range values are zero");
  const double slope = numerator / denominator;
  double residual = 0.0;
  for (std::size_t i = 0; i < x.size(); ++i)
    residual +=
        weights[i] * std::pow(y[i] - slope * x[i], 2);
  const double variance = residual / std::max<std::size_t>(1, x.size() - 1);
  return {slope, std::sqrt(std::max(0.0, variance / denominator))};
}

int main(int argc, char **argv) {
  try {
    fs::path reference_path;
    fs::path candidate_path;
    fs::path output;
    fs::path scores_output;
    double bin_width = 5.0;
    double reference_max_range = 30.0;
    double maximum_volume = 5.0;
    double x_limit = 50.0;
    double y_limit = 10.0;
    std::string input_type = "volume";
    int minimum_reference_tracks_per_bin = 1;
    thickness::QualityCuts cuts;
    for (int i = 1; i < argc; ++i) {
      const std::string argument = argv[i];
      auto next = [&]() -> std::string {
        if (++i >= argc)
          throw std::runtime_error("missing value after " + argument);
        return argv[i];
      };
      if (argument == "-o" || argument == "--output")
        output = next();
      else if (argument == "--scores-output")
        scores_output = next();
      else if (argument == "--bin-width-um")
        bin_width = std::stod(next());
      else if (argument == "--reference-max-range-um")
        reference_max_range = std::stod(next());
      else if (argument == "--maximum-volume-um3")
        maximum_volume = std::stod(next());
      else if (argument == "--x-limit-um")
        x_limit = std::stod(next());
      else if (argument == "--y-limit-um3")
        y_limit = std::stod(next());
      else if (argument == "--input-type")
        input_type = next();
      else if (argument == "--minimum-reference-tracks-per-bin")
        minimum_reference_tracks_per_bin = std::stoi(next());
      else if (thickness::is_quality_cut_option(argument))
        thickness::set_quality_cut(cuts, argument, next());
      else if (reference_path.empty())
        reference_path = argument;
      else if (candidate_path.empty())
        candidate_path = argument;
      else
        throw std::runtime_error("unexpected argument: " + argument);
    }
    if (reference_path.empty() || output.empty()) {
      std::cerr << "Usage: volume_range_root REFERENCE [CANDIDATE] -o PLOT "
                   "[--scores-output CSV]\n";
      return 2;
    }
    thickness::validate_quality_cuts(cuts);
    if (input_type != "volume" && input_type != "thickness")
      throw std::runtime_error("--input-type must be volume or thickness");
    if (input_type == "volume" && cuts.requested())
      throw std::runtime_error("fit-quality cuts require thickness input");
    if (minimum_reference_tracks_per_bin < 1)
      throw std::runtime_error(
          "--minimum-reference-tracks-per-bin must be at least one");

    const auto reference = load_analysis(reference_path, input_type, cuts);
    std::vector<double> mean_x, mean_y, std_x, std_y;
    std::vector<int> track_counts;
    const auto mean = [](const std::vector<double> &values) {
      double sum = 0.0;
      for (double value : values)
        sum += value;
      return sum / values.size();
    };
    const auto standard_deviation = [&](const std::vector<double> &values) {
      const double center = mean(values);
      double sum = 0.0;
      for (double value : values)
        sum += (value - center) * (value - center);
      return std::sqrt(sum / values.size());
    };
    for (double low = 0; low < reference_max_range; low += bin_width) {
      std::map<int, std::vector<VolumeRecord>> per_track;
      for (const auto &row : reference) {
        if (row.range_um >= low && row.range_um < low + bin_width &&
            row.range_um <= reference_max_range &&
            row.volume_um3 <= maximum_volume)
          per_track[row.track_id].push_back(row);
      }
      if (static_cast<int>(per_track.size()) <
          minimum_reference_tracks_per_bin)
        continue;
      std::vector<double> x_values, y_values;
      for (const auto &[track_id, rows] : per_track) {
        (void)track_id;
        std::vector<double> track_x, track_y;
        for (const auto &row : rows) {
          track_x.push_back(row.range_um);
          track_y.push_back(row.volume_um3);
        }
        x_values.push_back(mean(track_x));
        y_values.push_back(mean(track_y));
      }
      mean_x.push_back(mean(x_values));
      mean_y.push_back(mean(y_values));
      std_x.push_back(standard_deviation(x_values));
      std_y.push_back(standard_deviation(y_values));
      track_counts.push_back(static_cast<int>(per_track.size()));
    }
    if (mean_x.size() < 2)
      throw std::runtime_error("reference data populated fewer than two bins");
    const Fit reference_fit = fit_origin(mean_x, mean_y, &std_y);

    gROOT->SetBatch(kTRUE);
    gStyle->SetOptStat(0);
    TCanvas canvas("volume_range", "Volume versus range", 900, 680);
    TMultiGraph multigraph;
    TGraphErrors reference_graph(
        static_cast<int>(mean_x.size()), mean_x.data(), mean_y.data(),
        std_x.data(), std_y.data());
    reference_graph.SetMarkerStyle(20);
    reference_graph.SetMarkerColor(kBlack);
    reference_graph.SetLineColor(kGray + 2);
    const auto [minimum_tracks, maximum_tracks] =
        std::minmax_element(track_counts.begin(), track_counts.end());
    const std::string reference_title =
        "reference (per-track bins; N=" + std::to_string(*minimum_tracks) +
        "-" + std::to_string(*maximum_tracks) + ")";
    reference_graph.SetTitle(reference_title.c_str());
    multigraph.Add(&reference_graph, "P");

    std::array<double, 2> fit_x{0.0, x_limit};
    std::array<double, 2> fit_y{0.0, reference_fit.slope * x_limit};
    TGraph fit_graph(2, fit_x.data(), fit_y.data());
    fit_graph.SetLineColor(kBlue + 1);
    fit_graph.SetLineStyle(2);
    fit_graph.SetTitle("reference linear fit");
    multigraph.Add(&fit_graph, "L");

    std::vector<std::unique_ptr<TGraph>> candidate_graphs;
    std::vector<std::tuple<int, std::size_t, Fit, double, double>> scores;
    if (!candidate_path.empty()) {
      std::map<int, std::vector<VolumeRecord>> grouped;
      for (const auto &row : load_analysis(candidate_path, input_type, cuts))
        if (row.volume_um3 <= maximum_volume)
          grouped[row.track_id].push_back(row);
      int color = kRed + 1;
      for (auto &[track_id, rows] : grouped) {
        std::sort(rows.begin(), rows.end(),
                  [](const auto &a, const auto &b) {
                    return a.range_um < b.range_um;
                  });
        std::vector<double> x, y;
        for (const auto &row : rows) {
          x.push_back(row.range_um);
          y.push_back(row.volume_um3);
        }
        auto graph = std::make_unique<TGraph>(
            static_cast<int>(x.size()), x.data(), y.data());
        graph->SetMarkerStyle(5);
        graph->SetMarkerColor(color);
        graph->SetLineColor(color);
        graph->SetTitle(("candidate track " + std::to_string(track_id)).c_str());
        multigraph.Add(graph.get(), "LP");
        const Fit candidate_fit = fit_origin(x, y);
        const double reference_z =
            reference_fit.error > 0
                ? (candidate_fit.slope - reference_fit.slope) /
                      reference_fit.error
                : std::numeric_limits<double>::quiet_NaN();
        const double combined_error =
            std::hypot(reference_fit.error, candidate_fit.error);
        const double combined_z =
            combined_error > 0
                ? (candidate_fit.slope - reference_fit.slope) / combined_error
                : std::numeric_limits<double>::quiet_NaN();
        scores.emplace_back(track_id, rows.size(), candidate_fit, reference_z,
                            combined_z);
        candidate_graphs.push_back(std::move(graph));
        ++color;
      }
    }

    multigraph.SetTitle("Track volume versus range;Range [#mum];Cumulative "
                        "volume [#mum^{3}]");
    multigraph.Draw("A");
    multigraph.GetXaxis()->SetLimits(0, x_limit);
    multigraph.SetMinimum(0);
    multigraph.SetMaximum(y_limit);
    TLegend legend(0.15, 0.70, 0.52, 0.88);
    legend.SetHeader(
        ("reference slope=" + std::to_string(reference_fit.slope)).c_str());
    legend.AddEntry(&reference_graph, reference_title.c_str(), "lep");
    legend.AddEntry(&fit_graph, "reference linear fit", "l");
    for (const auto &graph : candidate_graphs)
      legend.AddEntry(graph.get(), graph->GetTitle(), "lp");
    legend.Draw();
    canvas.SaveAs(output.string().c_str());

    if (!scores_output.empty()) {
      std::ofstream scores_file(scores_output);
      scores_file << "track_id,n_volume_points,slope_um2,slope_error_um2,"
                     "reference_slope_um2,reference_slope_error_um2,"
                     "slope_ratio,reference_z_score,"
                     "combined_uncertainty_z_score,"
                     "consistent_with_reference_3sigma\n";
      for (const auto &[track_id, count, candidate_fit, reference_z,
                        combined_z] : scores)
        scores_file << track_id << ',' << count << ',' << candidate_fit.slope
                    << ',' << candidate_fit.error << ',' << reference_fit.slope
                    << ',' << reference_fit.error << ','
                    << candidate_fit.slope / reference_fit.slope << ','
                    << reference_z << ',' << combined_z << ','
                    << (std::abs(combined_z) <= 3.0 ? "true" : "false")
                    << '\n';
    }
    std::cout << "Wrote " << output
              << "; reference slope = " << reference_fit.slope << " +/- "
              << reference_fit.error << " um^2\n";
  } catch (const std::exception &error) {
    std::cerr << "error: " << error.what() << '\n';
    return 1;
  }
  return 0;
}
