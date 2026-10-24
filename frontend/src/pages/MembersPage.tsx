import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Role } from "@/lib/types";
import { timeAgo } from "@/lib/format";
import { useMe } from "@/hooks/useSession";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Field, Input, Select } from "@/components/ui/Input";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { Callout } from "@/components/ui/Callout";
import { Modal, useConfirm } from "@/components/ui/Dialog";

export default function MembersPage() {
  const me = useMe().data;
  const qc = useQueryClient();
  const confirm = useConfirm();
  const users = useQuery({ queryKey: ["users"], queryFn: api.users });
  const [inviteOpen, setInviteOpen] = useState(false);

  const update = useMutation({
    mutationFn: ({ id, role }: { id: string | number; role: Role }) => api.updateUser(id, { role }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
    onError: (e: Error) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: api.deleteUser,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6">
      <PageHeader
        title="Members"
        description="People who can ask questions in this workspace. Admins can also manage data, AI and members."
        action={
          <Button onClick={() => setInviteOpen(true)}>
            <UserPlus className="h-4 w-4" /> Add member
          </Button>
        }
      />
      {users.isPending ? (
        <Spinner className="h-5 w-5 text-muted" />
      ) : users.isError ? (
        <Callout tone="danger">{users.error.message}</Callout>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead className="bg-surface-2 text-left text-[12px] text-muted">
                <tr>
                  <th scope="col" className="px-4 py-2 font-medium">Name</th>
                  <th scope="col" className="px-4 py-2 font-medium">Role</th>
                  <th scope="col" className="hidden px-4 py-2 font-medium sm:table-cell">Joined</th>
                  <th scope="col" className="px-4 py-2"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {users.data.users.map((u) => {
                  const self = u.id === me?.id;
                  return (
                    <tr key={u.id}>
                      <td className="px-4 py-3">
                        <div className="font-medium">{u.name || "—"} {self && <span className="text-muted">(you)</span>}</div>
                        <div className="text-[12px] text-muted">{u.email}</div>
                      </td>
                      <td className="px-4 py-3">
                        <Select
                          aria-label={`Role for ${u.email}`}
                          className="h-8 w-[120px] text-[13px]"
                          value={u.role}
                          disabled={self || update.isPending}
                          onChange={(e) => update.mutate({ id: u.id, role: e.target.value as Role })}
                        >
                          <option value="member">Member</option>
                          <option value="admin">Admin</option>
                        </Select>
                      </td>
                      <td className="hidden px-4 py-3 text-muted sm:table-cell">{timeAgo(u.created_at)}</td>
                      <td className="px-4 py-3 text-right">
                        {!self && (
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={`Remove ${u.email}`}
                            onClick={async () => {
                              if (await confirm({ title: "Remove member?", description: `${u.email} will lose access immediately.`, confirmLabel: "Remove", danger: true })) remove.mutate(u.id);
                            }}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      <InviteDialog open={inviteOpen} onClose={() => setInviteOpen(false)} />
    </div>
  );
}

function InviteDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("member");
  const create = useMutation({
    mutationFn: () => api.createUser({ email: email.trim(), name: name.trim(), password, role }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success(`${r.user.email} added. Share their temporary password securely.`);
      setEmail("");
      setName("");
      setPassword("");
      setRole("member");
      onClose();
    },
  });

  return (
    <Modal open={open} onClose={onClose} labelledBy="invite-title">
      <h2 id="invite-title" className="text-[15px] font-semibold">Add member</h2>
      <p className="mt-1 text-[13px] text-muted">They can sign in right away with the temporary password you set.</p>
      <form
        className="mt-5 space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <Field label="Email" htmlFor="inv-email">
          <Input id="inv-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Name" htmlFor="inv-name">
          <Input id="inv-name" required value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Temporary password" htmlFor="inv-pw" help="At least 10 characters.">
          <Input id="inv-pw" type="password" autoComplete="new-password" minLength={10} required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Field label="Role" htmlFor="inv-role">
          <Select id="inv-role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="member">Member: can ask questions</option>
            <option value="admin">Admin: full access</option>
          </Select>
        </Field>
        {create.isError && <Callout tone="danger">{create.error.message}</Callout>}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={create.isPending}>Add member</Button>
        </div>
      </form>
    </Modal>
  );
}
