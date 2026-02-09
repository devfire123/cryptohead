#include "emp-tool/emp-tool.h"
#include "emp-zk/emp-zk.h"

#include <cstdlib>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

using namespace emp;
using namespace std;

static constexpr int threads = 1;

static vector<uint64_t> parse_u64_csv(const string &s) {
  vector<uint64_t> out;
  string item;
  stringstream ss(s);
  while (getline(ss, item, ',')) {
    if (item.empty())
      continue;
    out.push_back(strtoull(item.c_str(), nullptr, 0));
  }
  return out;
}

int main(int argc, char **argv) {
  (void)argc;
  (void)argv;

  cerr << "[submit] start\n" << flush;

  const char *gs = getenv("SLOWGOLD_GUESSES");
  if (!gs) {
    cerr << "need SLOWGOLD_GUESSES=comma,separated,10,values\n";
    return 2;
  }
  vector<uint64_t> guesses = parse_u64_csv(gs);
  if (guesses.size() != 10) {
    cerr << "need exactly 10 guesses, got " << guesses.size() << "\n";
    return 2;
  }

  uint64_t X = 0;
  if (const char *xs = getenv("SLOWGOLD_X")) {
    X = strtoull(xs, nullptr, 0);
  }

  int party = BOB;
  const char *host = getenv("SLOWGOLD_HOST");
  if (!host)
    host = "34.169.138.235";
  int port = 31183;

  BoolIO<NetIO> *ios[threads];
  for (int i = 0; i < threads; ++i) {
    ios[i] = new BoolIO<NetIO>(new NetIO(party == ALICE ? nullptr : host, port),
                              party == ALICE);
  }
  cerr << "[submit] netio ready\n" << flush;

  setup_zk_arith<BoolIO<NetIO>>(ios, threads, party);
  cerr << "[submit] setup done\n" << flush;

  vector<IntFp> array1, array2;
  for (int i = 0; i < 10; i++) {
    array1.push_back(IntFp(0, ALICE));
    array2.push_back(IntFp(0, ALICE));
  }

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
  cerr << "[submit] zkp done\n" << flush;

  for (int i = 0; i < 10; i++) {
    uint64_t g = guesses[i];
    ios[0]->io->send_data(&g, sizeof(uint64_t));
  }
  cerr << "[submit] guesses sent\n" << flush;

  // Flag is always exactly 46 bytes in the challenge.
  string flag;
  flag.resize(46);
  cerr << "[submit] waiting flag...\n" << flush;
  ios[0]->io->recv_data(&flag[0], 46);
  cerr << "[submit] flag recv\n" << flush;
  cout << flag;

  for (int i = 0; i < threads; ++i) {
    delete ios[i]->io;
    delete ios[i];
  }
  return 0;
}
