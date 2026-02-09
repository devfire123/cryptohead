#include "emp-tool/emp-tool.h"
#include "emp-zk/emp-zk.h"

#include <cinttypes>
#include <cstdlib>
#include <iostream>
#include <vector>

using namespace emp;
using namespace std;

static constexpr int threads = 1;

int main(int argc, char **argv) {
  (void)argc;
  (void)argv;

  int party = BOB;
  const char *host = getenv("SLOWGOLD_HOST");
  if (!host)
    // NetIO uses inet_addr() and does not resolve hostnames.
    host = "34.169.138.235";
  int port = 31183;

  uint64_t X = 0;
  if (const char *xs = getenv("SLOWGOLD_X")) {
    X = strtoull(xs, nullptr, 0);
  } else {
    // Fallback: read from stdin like the original client.
    cin >> X;
  }

  BoolIO<NetIO> *ios[threads];
  for (int i = 0; i < threads; ++i) {
    ios[i] = new BoolIO<NetIO>(new NetIO(party == ALICE ? nullptr : host, port),
                              party == ALICE);
  }

  setup_zk_arith<BoolIO<NetIO>>(ios, threads, party);

  vector<IntFp> array1, array2;
  for (int i = 0; i < 10; i++) {
    array1.push_back(IntFp(0, ALICE));
    array2.push_back(IntFp(0, ALICE));
  }

  // Send X as a public challenge.
  ZKFpExec::zk_exec->send_data(&X, sizeof(uint64_t));

  IntFp acc1 = IntFp(1, PUBLIC);
  IntFp acc2 = IntFp(1, PUBLIC);
  for (int i = 0; i < 10; i++) {
    acc1 = acc1 * (array1[i] + X);
    acc2 = acc2 * (array2[i] + X);
  }
  IntFp final_zero = acc1 + acc2.negate();
  batch_reveal_check_zero(&final_zero, 1);

  finalize_zk_arith<BoolIO<NetIO>>();

  // Emit the pieces we need for the offline solver.
  const uint64_t delta = slowgold_last_delta_u64();
  const uint64_t seed = slowgold_last_mulcheck_seed();
  const uint64_t U = slowgold_last_mulcheck_U();
  const uint64_t V = slowgold_last_mulcheck_V();
  const uint64_t ka = slowgold_last_mulcheck_ka();
  const uint64_t kb = slowgold_last_mulcheck_kb();
  const uint64_t kc = slowgold_last_mulcheck_kc();

  // One JSON line; stable to parse.
  cout << "{"
       << "\"X\":" << X << ","
       << "\"delta\":" << delta << ","
       << "\"seed\":" << seed << ","
       << "\"U\":" << U << ","
       << "\"V\":" << V << ","
       << "\"ka\":" << ka << ","
       << "\"kb\":" << kb << ","
       << "\"kc\":" << kc << "}"
       << "\n";

  for (int i = 0; i < threads; ++i) {
    delete ios[i]->io;
    delete ios[i];
  }
  return 0;
}
