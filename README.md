## Lean Info Scrapper

This is a script which basically mines information from Lean files which can be used for statistics about Lean and training a machine learning agent on Lean proofs.

Specifically it runs the Lean server on every `.lean` file in the various Lean paths and executes the "info" request on every position in that file.  The results are packaged into compressed JSON files.

## Data being stored
If you are familiar with Lean and the Lean server, you are familiar with the information stored by this script.  Everytime in Lean (in VS Code, Emacs, or the various online editors), when you click or hover on a character, it shows the tactic state on the side and hover text with type information.  This is the information being scrapped.  

For example, consider [line 140 of init/algebra/ring](https://github.com/leanprover/lean/blob/ceacfa7445953cbc8860ddabc55407430a9ca5c3/library/init/algebra/ring.lean#L140):
```lean
  begin rw mul_comm, exact dvd_mul_of_dvd_left h _ end
```
If one clicks in VS code just after the comma, Lean displays the following Tactic State:
```lean
1 goal
α : Type u,
_inst_1 : comm_semiring α,
a b : α,
h : a ∣ b,
c : α
⊢ a ∣ b * c
```
This continues for all the characters in `exact dvd_mul_of_dvd_left h _`.  Moreover, if one hovers over `exact`, the tooltip (at least in VS Code) displays information for the `exact` tactic, including the doc string and the parameters.  If one hovers over `dvd_mul_of_dvd_left`, the tooltip displays the full name and full type of the theorem.  If one ctrl-clicks on the theorem, it will take you to where it is defined.  All of this information is being passed to the editor via an "info" request to the Lean server.  This script captures this information.

There are currently eight types of information returned by an "info" request.
* 'full-id' (string): The full name of a name, e.g. `dvd.intro`, (whether a theorem, an assumption in the local context, a definition, etc)
* 'source' (dictionary): The specific location (file, line, column) where a identifier is defined.
* 'type' (string): The type of an identifier.  If that identifer is for a theorem, the type is the theorem.
* 'text' (string): The text of a tactic (e.g. "simp")
* 'doc' (string): The doc string for an identifer.  (Usually for a tactic, but also for some other things.)
* 'tactic_params' (list): The parameters of a tactic, e.g. `['!?', 'only?', '(* | [(* | (- id | expr)), ...]?)', '(with id*)?', '(at (* | (⊢ | id)*))?', 'tactic.simp_config_ext?']` for the simp tactic.
* 'tactic_param_idx' (int): Marks which tactic parameter that position is in.
* 'state' (string): The tactic state as it appears on the side of VS Code.

**NB**: This script passes the option `pp.all = true` to the Lean server.  This means all the content will use the fully elaborated pretty-printed version of, say, the goals.  If one wishes to run this script without that setting (or with different options), it shouldn't be hard to modify the script. Just search for where `pp.all` is used.

The data is stored as a JSON list for each file.  Here is an example of one element of that list:
```json
{
    "file": "/Users/ec2-user/.elan/toolchains/3.4.2/lib/lean/library/init/algebra/ring.lean", 
    "pos1": 4428, 
    "line1": 140, 
    "col1": 20,
    "pos2": 4460, 
    "line2": 140, 
    "col2": 52,  
    "info_type": "state", 
    "info_content": "α : Type u,\n_inst_1 : comm_semiring.{u} α,\na b : α,\nh : @has_dvd.dvd.{u} α (@comm_semiring_has_dvd.{u} α _inst_1) a b,\nc : α\n⊢ @has_dvd.dvd.{u} α (@comm_semiring_has_dvd.{u} α _inst_1) a\n    (@has_mul.mul.{u} α\n       (@semigroup.to_has_mul.{u} α\n          (@comm_semigroup.to_semigroup.{u} α\n             (@comm_monoid.to_comm_semigroup.{u} α (@comm_semiring.to_comm_monoid.{u} α _inst_1))))\n       b\n       c)", 
    "string": ", exact dvd_mul_of_dvd_left h _ ", "_timestamp": "2020-02-22T00:38:09.450564", 
    "_lean_version": "3.4.2", 
    "_mathlib_git": "https://github.com/leanprover/mathlib", 
    "_mathlib_rev": "dd8da5165bd00b07408dbb87173e96908c6926a4"
}
```
Here is a description of the various fields:
* 'file' (string): The file being processed.
* 'pos1', 'line1', 'col1' (int): The first character position to return this message, one-indexed.  (Note, the Lean server uses one-indexing for lines and zero-indexing for columns.  We convert everything to one-indexing.)
* 'pos2', 'line2', 'col2' (int): One after the last character position which returns this message, one-indexed.
* 'info_type' (string): The type of the information.
* 'info_content' (varies): The content of the information.
* 'string': The snippet of the file which is spanned by this message.  For a 'state' message, it is usually (but not always because of special cases with `rw` and `;`) the full tactic command applied to that goal state.
* '_timestamp' (string): The datetime that this information was accessed from the Lean server.  (More useful for debugging this script than anything else.)
* '_lean_version' (string): The version of Lean being used.  Useful for reproducibility.  Taken from `leanpkg.toml`.  (The Lean version will determine the files in the core library and also the behavior of the Lean server.)
* '_mathlib_git', '_mathlib_rev' (string): The git version of mathlib.  Useful for reproducibility.  Taken from `leanpkg.toml`.  (Note, [https://github.com/leanprover/mathlib](https://github.com/leanprover/mathlib) redirects to [https://github.com/leanprover-community/mathlib](https://github.com/leanprover/mathlib) and that [dd8da5165bd00b07408dbb87173e96908c6926a4](https://github.com/leanprover-community/mathlib/tree/dd8da51
) is a fairly recent commit of the new Lean community mathlib.

## TODO: Extract useful information from this data
This data is very raw.  The next step is to parse it into a more useful form, including the following tasks:
* Parse the goal states so that they can be entered back into the Lean as `theorem`s to prove.
* Parse all 'full-id' messages which correspond to theorems, again for entering back into Lean.  (The main issue is to find the universe parameters.)
* Match goal states with the first tactic applied to that state.  This will be a great machine learning data set.
* Match goal states with the premises applied to them.  Again, this will be very useful for machine learning.
* Get the full tactic string applied to each goal.  Possibly parse into more machine-accessible form.

This is being actively worked on and such extraction scripts will be added to this repository.

## How to run this script

### Set up Lean (if not already done)
See [here](https://github.com/leanprover-community/mathlib/tree/master#installation) for instructions on how to set up Lean for the first time.

You will need to be able to run `update-mathlib`.  It is not clear to me the best way to set this up, but `sudo pip3 install mathlibtools` seems to work.

### Set up this repository
```bash
# download locally
git clone https://github.com/jasonrute/lean_info_scrapper.git
cd lean_info_scrapper

# set it up for lean 
# (change the leanpkg.toml if desired to run on a particular version of lean or mathlib)
leanpkg configure  # get lean working for this repository
update-mathlib     # fetches the mathlib files including .olean files
```

### Running the script
To run on a single `.lean` file, call the script as follows.  (Must use the full path of lean file.  It will complain otherwise.)  Saves the `.json.gz` file to `data-directory`.
```bash
python3 scapper.py full_path_file.lean data-directory
```

To run on a directory, call the script as follows.  (Must use the full path of lean directory.  It will complain otherwise.)  Saves the `.json.gz` files to `data-directory`.  It will skip over all files which have already been processed.  (If you don't want this behavior, point to a new data directory.)
```bash
python3 scapper.py full_path_to_lean_or_mathlib_subdirectory data-directory
```

To run on all `.lean` files in the core library and mathlib (and `src` if you add files there), run with `ALL` in place of a file/directory.  Saves the `.json.gz` files to `data-directory`.  It will skip over all files which have already been processed.  (If you don't want this behavior, point to a new data directory.)
```bash
python3 scapper.py ALL data-directory
```

## Getting access to the data
One can run the script themselves (it takes about 24 hours for all of mathlib and the core Lean library).  Alternately, I'm happy to share the information privately to those who contact me on the Lean Zulip channel.  It is less than 100 MB when compressed.

**NB:** Since the data contains significant snippets of Lean files, the data probably has the same copyright as the `lean` and `mathlib` repositories.
